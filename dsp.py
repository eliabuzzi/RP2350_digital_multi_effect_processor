import array

#   ALLOCAZIONE DEI BUFFER AUDIO COMME PRIMISSIMA COSA



# MEMORIA RIVERBERO
BUFFER_LENGTH_REV = 0x5020 #(20512 = 8*2048 + 4*1024 + 32)
reverb_buffer = array.array('i', [0] * BUFFER_LENGTH_REV)

# MEMORIA DELAY
BUFFER_LENGTH_ECHO = 0x8020 # 32768 + 32
delay_buffer = array.array('h', [0] * BUFFER_LENGTH_ECHO)

# MEMORIA FREQUENCY SHIFTER
BUFFER_LENGTH_SHIFTER = 2112
shifter_buffer = array.array('i', [0] * BUFFER_LENGTH_SHIFTER)

# MEMORIA MUTO
mute_state = array.array('I', [256])            # 256 = VOLUME MASSIMO

# MEMORIA BITCRUSHER
bitcrusher_state = array.array('i', [0] * 8)

import machine
import math
import _thread
import dsp_viper_passthrough
import dsp_viper_reverb
import dsp_viper_delay
import dsp_viper_mute
import dsp_viper_bitcrusher
import dsp_viper_frequency_shifter
#import dsp_viper_memory_flush
import DMA_FLUSH

from core_events import wait_event

from pads_config import pad_configuration
from PIO_DAC import pio_dac
from PIO_ADC import pio_adc
from DMA_ADC import dma_adc
from DMA_DAC import dma_dac



import time
#import uctypes

# NOTA: IL CORE 0 (UI E CONFIGURAZIONI) DEVE GIÀ MACINARE I PARAMETRI E GESTIRE QUALE DELLE DUE CONFIGURAZIONI È ATTIVA
# VIPER NON CALCOLA MS->N CAMPIONI MA HA GIÀ QUEL DATO, IL THREAD PYTHON LEGGE L'INDIRIZZO INIZIALE DELLA CONFIGURAZIONE ATTIVA E LO 
# PASSA A VIPER GIA' IMPOSTATO SUL BANCO GIUSTO

# CREO IL THREAD PYTHON PER GESTIRE IL DSP

# CONFIGURAZIONE PARAMETRI
BLOCK_SIZE = 64#256                 # SUCCESSIVAMENTE = DMA_WORDS
N_BLOCKS = 64#16                    # SUCCESSIVAMENTE SARA' dim_buffer (byte) / block_size * 4 byte
WRAP_MASK = N_BLOCKS - 1            # IN QUESTO CASO 15: 1111 o 0x000F

# CONFIGURAZIONE MAILBOX (MEMORY MAP HW), OFFEST DI 4 byte per parola (0x04)
# IN MEMORIA ABBIAMO DUE MAILBOX (A e B), UNA ATTIVA (QUELLA CHE LEGGE IL DSP) E UNA A RIPOSO (QUELLA CHE PYTHON MODIFICA)
# IN QUESTO MODO AVREMO LA CERTEZZA CHE NON VERRANNO SOVRASCRITTE CONFIGURAZIONI MENTRE IL DSP ASPETTA

MAILBOX_BASE = 0x2007C000       # EQ A CTRL_REG
BYPASS_BASE = MAILBOX_BASE + 0x10
BANK_STRIDE = 0x08


ADDR_DMA_INDEX = MAILBOX_BASE + 0x00       # SCRITTO DALL'IRQ HANDLER DEL DMA
ADDR_ACTIVE_CONFIG = MAILBOX_BASE + 0x04    # SCRITTO DAL CORE 0 (0 = BANCO A, 1 = BANCO B)

# BANCHI DI CONFIGURAZIONE (PING-PONG)
BANK_A_BASE = MAILBOX_BASE + 0x08           # BANCO A   
BANK_B_BASE = MAILBOX_BASE + 0x14           # BANCO B 

# OFFSET INTERNI AI BANCHI A/B PER ACCEDERE AI VARI PARAMETRI
EFFECT_SEL_OFFSET = 0x00
EFFECT_PARAM_OFFSET = 0x04
BLOCK_SIZE_OFFSET = 0x08

# REGISTRO PER IL PRE-ROLL
N_PREROLL = 5


#ADDR_WRITE_OFFSET = MAILBOX_BASE + 0x04    # NON SERVE SE USO GLI STESSI INDICI
#ADDR_EFFECT_SEL = MAILBOX_BASE + 0x04
#ADDR_EFFECT_PARAM = MAILBOX_BASE + 0x08
#ADDR_BLOCK_SIZE = MAILBOX_BASE + 0x0C

# AZZERA I REGISTRI DURANTE IL BOOT
#machine.mem32[ADDR_READ_INDEX] = 0
#machine.mem32[ADDR_WRITE_OFFSET] = 0
#machine.mem32[ADDR_EFFECT_SEL] = 0
#machine.mem32[ADDR_EFFECT_PARAM] = 0
#machine.mem32[ADDR_BLOCK_SIZE] = BLOCK_SIZE

# LUCCHETTO PER LA SINCRONIZZAZIONE (MUTEX)
#dsp_lock = _thread.allocate_lock()
#dsp_lock.acquire(True)                  # LOCK BLOCCANTE

# STATISTICHE PER VERIFICA DEL BUDGET TEMPORALE

MAX_RECORDS = 512
record_index = 0
dsp_elaboration_time =  array.array('I', [0] * MAX_RECORDS)
flush_time = array.array('I', [0] * 64)
flush_index = 0

preroll_time = 0

# INIZIALIZZAZIONE DEI BLOCCHI DI CONTROLLO
sm_adc = None
sm_dac = None
dma_rx = None
dma_tx = None




#lag_log = array.array('i', [0]*64); lag_i = 0
#cnt = 0

VOLUME_SLOT = MAILBOX_BASE + 0x0C


# CREAZIONE DELLA LUT PER IL SENO
SINE_BASE = 64
SINE_SIZE = 2048
#BUFFER_LENGTH = SINE_BASE + SINE_SIZE      # 2112 WORD
def init_frequency_shifter_buffer(buffer):
  
    for n in range(SINE_SIZE):
        buffer[SINE_BASE + n] = int(math.floor(32767 * math.sin(2 * math.pi * n / SINE_SIZE) + 0.5))





# THREAD PYTHON PER IL DSP (CORE 1)
def dsp_thread():
    global record_index, sm_adc, sm_dac, dma_rx, dma_tx, cnt, lag_i, flush_index

    # VERIFICO SU QUALE CORE GIRA IL THREAD DEL DSP
    core_id = machine.mem32[0xD000_0000]
    print("DSP AVVIATO, CORE ", core_id)

    # CREAZIONE LUT PER IL FREQUENCY SHIFTER
    init_frequency_shifter_buffer(shifter_buffer)


    # MI FACCIO RITORNARE LE SM
    sm_adc = pio_adc()
    sm_dac = pio_dac()

    # CONFIGURAZIONE PAD
    pad_configuration()

    # DMA
    dma_rx = dma_adc(sm_adc)
    dma_tx = dma_dac(sm_dac)


    # AVVIO SM/DMA ADC, IN QUESTO MODO NON DOVREBBERO ESSERE DISTURBATE DAL CORE 0 E GLI INTERRUPT CHE GENERA L'I2C
    dma_rx.active(1)
    sm_adc.active(1)

    # INIZIO PREROLL
    t0 = time.ticks_us()

    read_index = 0                      # INDICE LOGICO LOCALE DEL DSP (INSEGUE L'INDICE DEL BLOCCO DEL DMA)

    # NUOVA GESTIONE DEL CAMBIO EFFETTO: IL THREAD PYTHON GESTISCE AUTONOMAMENTE LE VARIE FASI
    active_effect = 0
    fade_state = 0

    # FASE DI PRE-ROLL / WARM-UP (ESEGUITA UNA SOLA VOLTA PER DARE AL dma_tx UN PO' DI BLOCCHI DI MARGINE)
    # NOTA: EVITA DI VALUTARE UN FLAG INUTILMENTE OGNI VOLTA DENTRO AL WHILE TRUE

  
    while read_index < N_PREROLL:
        wait_event()                                        # DORMI FINCHÈ NON RICEVE UN EVENTO
        read_index = machine.mem32[ADDR_DMA_INDEX]          # AGGIORNA L'INDICE LOCALE PER VEDERE SE È FINITA LA FASE DI PREROLL

    # AZZERO L'INDICE DEL CONSUMATORE
    read_index = 0

    # AVVIO SM/DMA TX
    dma_tx.active(1)
    sm_dac.active(1)
    
    # FINE PREROLL
    preroll_time = time.ticks_diff(time.ticks_us(), t0)

    print("DURATA FASE DI PREROLL:", preroll_time)

    # ----------------------------------------------------------------------------------------------------------------------------------

    
    while True:
     

        # SLEEP IN ATTESA DEI NUOVI DATI DA ELABORARE
        while read_index == machine.mem32[ADDR_DMA_INDEX]:
            wait_event()

        #if (cnt & 0xFF) == 0 and lag_i < 64:
        #    adc_pos = ((dma_rx.write - 0x2006C000) >> 8) & WRAP_MASK
        #    dac_pos = ((dma_tx.read  - 0x20074000) >> 8) & WRAP_MASK
        #    lag_log[lag_i] = ((read_index - dac_pos) & WRAP_MASK) * 100 + ((adc_pos - read_index) & WRAP_MASK)
        #    lag_i += 1

        # RIATTIVAZIONE: ELABORA TUTTI I BLOCCHI ARRETRATI (NEL CASO IDEALE 1) FINO A RAGGIUNGERE IL DMA
        while read_index != machine.mem32[ADDR_DMA_INDEX]:

            # INIZIO TEMPO DI ELABORAZIONE
            t0 = time.ticks_us()

            # VERSIONE GLOBALE DELLA MAILBOX
            mailbox_version = machine.mem32[MAILBOX_BASE + 0x08]

            # RICHIESTA DELL'EFFETTO
            requested_effect = machine.mem32[MAILBOX_BASE + 0x04]

            # GESTIONE DELLA RICHIESTA DEL CAMBIO EFFETTO (SE NON SONO GIA' IN UNA TRANSIZIONE)
            if fade_state == 0 and requested_effect != active_effect:

                if active_effect != 0:
                    fade_state = 1                          # FADE OUT
                else:
                    active_effect = requested_effect       # TRANSIZIONE DELL'EFFETTO
                    fade_state = 2                          # FADE IN        

            # PUNTA ALLA CONFIGURAZIONE ATTIVA DELL'EFFETTO ATTIVO
            effect_base = BYPASS_BASE + (active_effect * 0x20)
            active_bank = machine.mem32[effect_base]                            # LEGGE QUALE DEI DUE BANCHI È ATTIVO

            parameter_base = effect_base + 0x04 + active_bank * BANK_STRIDE     # BASE PER I VALORI DEI PARAMETRI NEL BANCO ATTIVO


            # -------------------------------------------------------------------------------------------------------------------------


            # CHIAMATA AGLI ALGORITMI AUDIO TRAMITE VIPER, PASSO IL MINIMO INDISPENSABILE
            if active_effect == 0:     # MUTE

                # CHIAMA IL MUTO IN MOODALITÀ FADE OUT (TARGET_VOL = 0) E ACQUISIZIONE DAL BUFFER IN INGRESSO
                dsp_viper_mute.dsp_viper_mute(read_index, 0, mute_state, 0)


            elif active_effect == 1:   # BYPASS

                dsp_viper_passthrough.dsp_viper_bypass(read_index)


            elif active_effect == 2:   # REVERB
                
                dsp_viper_reverb.dsp_viper_reverb(read_index, mailbox_version, parameter_base, reverb_buffer)


            elif active_effect == 3:   # DELAY

                dsp_viper_delay.dsp_viper_delay(read_index, mailbox_version, parameter_base, delay_buffer)
                

            elif active_effect == 4:   # BITCRUSHER

                dsp_viper_bitcrusher.dsp_viper_bitcrusher(read_index, mailbox_version, parameter_base, bitcrusher_state)

            elif active_effect == 5:    # BODE FREQUENCY SHIFTER

                dsp_viper_frequency_shifter.dsp_viper_frequency_shifter(read_index, mailbox_version, parameter_base, shifter_buffer)

                


            # FADE-OUT: RAMPA LINEARE CHE PORTA L'USCITA A 0
            if fade_state == 1:

                # CHIAMA IL MUTO CON PARAMETRI VOLUME_TARGET = 0 E MODE = 1 (RISCRIVE L'USCITA)
                dsp_viper_mute.dsp_viper_mute(read_index, 0, mute_state, 1)

                if mute_state[0] == 0:

                    # FADE-OUT CONCLUSO: CHIAMO IL MUTO E FACCIO IL FLUSH DELLE MEMORIE
                    active_effect = 0                   # MUTO
                    fade_state = 3                      
                    
            # FADE-IN: RAMPA LINEARE CHE PORTA L'USCITA AL VOLUME MASSIMO
            elif fade_state == 2:

                dsp_viper_mute.dsp_viper_mute(read_index, 256, mute_state, 1)

                if mute_state[0] == 256:

                    fade_state = 0                      # RITORNA ALLA CONDIZIONE "RUNNING"
                    machine.mem32[VOLUME_SLOT] = 256

            elif fade_state == 3:                       # FLUSH

                DMA_FLUSH.dma_clear(reverb_buffer, 20512)
                DMA_FLUSH.dma_clear(delay_buffer, 16400)
                DMA_FLUSH.dma_clear(bitcrusher_state, 8)
                DMA_FLUSH.dma_clear(shifter_buffer, 64)

                fade_state = 0
                machine.mem32[VOLUME_SLOT] = 0      # NOTIFICA AL MAIN DI AVER FINITO IL FADE OUT                   



            # AVANZA L'INDICE LOCALE E APPLICA IL WRAP-AROUND
            read_index = (read_index + 1) & WRAP_MASK

            #cnt += 1

            #if record_index < MAX_RECORDS:
            dsp_elaboration_time[record_index] = time.ticks_diff(time.ticks_us(), t0)
            record_index = (record_index + 1) & 511

# NOTA SUL THREAD: AVEVO PENSATO DI PASSARE A VIPER IL COMPITO DI ELABORARE DIRETTAMENTE N BLOCCHI DI DATI AUDIO, ALLA FINE NON HA TANTO SENSO PERCHÈ DOVREI GESTIRE
# IL WRAP DELL'INDIRIZZO DI LETTURA DIRETTAMENTE DAL CICLO PIÙ INTERNO INSERENDO INEVITABILMENTE UN GRANDE OVERHEAD, FACENDO COSÌ (IL THREAD PYTHON PASSA UN SOLO BLOCCO ALLA VOLTA A VIPER)
# MI RISPARMIO QUESTA PROBLEMATICA E GARANTISCO CHE GLI INDIRIZZI IN MEMORIA SIANO SEMPRE CONTIGUI, OLTRETUTTO IL DSP DOVREBBE CONCETTUALMENTE ELABORARE UN BLOCCO ALLA VOLTA E FINIRE PRIMA DEL DMA
# QUESTA È SOLO UNA MISURA DI TUTELA (NEL CASO IN CUI IL CORE 0 BLOCCHI I BUS RAM PER UN ATTIMO O CI SIANO EFFETTI PESANTI DA ELABORARE) PER PERMETTERE AL DSP DI NON PERDERSI NESSUN BLOCCO DI DATI ANCHE SE 
# DOVESSE ESSERE LEGGERMENTE IN RITARDO

# AVVIO DEL THREAD SUL CORE 1
def start_dsp():
    _thread.start_new_thread(dsp_thread, ())

def stop_dsp():
    global sm_adc, sm_dac, dma_rx, dma_tx

    # Disattiva la SM:
    sm_adc.active(0)
    
    # Disattiva il DMA:
    dma_rx.active(0)
    
    # SICUREZZA PER EVITARE POP/GLITCH AUDIO
    time.sleep_ms(30)

    # CONCLUDE LA DISATTIVAZIONE DEI MODULI
    dma_tx.active(0)
    sm_dac.active(0)

