import sys
import gc

# CLEANUP PREVENTIVO
sys.modules.clear()
gc.collect()

import dsp         # ALLOCA SUBITO I BUFFER AUDIO
gc.collect()            # PULISCE L'HEAP PER LE SUCCESSIVE ALLOCAZIONI

#from ui_display import LCDscreen

from ui_led import EffectLed
from Encoder import Encoder
from mailbox_writer import Mailbox
from ADC_pot import Read_ADC
import time
import mailbox_writer
from machine import Pin, mem32, freq
import uctypes

#from pads_config import pad_configuration
#from PIO_DAC import pio_dac
#from PIO_ADC import pio_adc
#from DMA_ADC import dma_adc
#from DMA_DAC import dma_dac

from sine_generator import SinePWM, Impulse, SoftPulsePWM
import array

# PER DEBUG, VERIFICA INDIRIZZI
gc.collect()
#print("allocati:", gc.mem_alloc(), "free: ", gc.mem_free())
print("INDIRIZZI BUFFER EFFETTI")
for n, b in (("rev", dsp.reverb_buffer), ("dly", dsp.delay_buffer), ("mute", dsp.mute_state), ("bitc", dsp.bitcrusher_state), ("freq shift", dsp.shifter_buffer)):
    print(n, hex(uctypes.addressof(b)))
print("\n")



# CODICE PYTHON PER GESTIRE IL CORE 0, ESSO HA IL COMPITO DI INIZIALIZZARE L'INTERO SISTEMA, GESTIRE L'ACQUISIZIONE DEI PARAMETRI E DEL SELETTORE DELL'EFFETTO
# CONVERTIRE I PARAMETRI IN FORMATO Q15 PRONTO PER ESSERE LETTO DAL DSP, AGGIORNARE LO SCHERMO E GESTIRE LE CONFIGURAZIONI NELLA MAILBOX

# INIZIALIZZAZIONE

DMA_WORDS = 64 # BLOCK_SIZE

ADC_MIN = 0x0000
ADC_MID = 0x7FFF
ADC_MAX = 0xFFFF

SYS_CLK = 144_000_000 
freq(SYS_CLK) 

# MODALITA' SLAVE / I2S (ADC)
FMT_PIN = 18
MD0_PIN = 19
MD1_PIN = 20

fmt = Pin(FMT_PIN, Pin.OUT)
md0 = Pin(MD0_PIN, Pin.OUT)
md1 = Pin(MD1_PIN, Pin.OUT)

# INIZIALIZZAZIONE PIN
fmt.value(0)
md0.value(0)
md1.value(0)

# SOFT MUTE ATTIVATO
XSMT_PIN = 17

xsmt = Pin(XSMT_PIN, Pin.OUT)
xsmt.value(0)


# VARIABILI DI STATO PER RILEVARE LA SELEZIONE DI UN EFFETTO (QUANDO L'ENCODER VIENE RUOTATO)
delta = 0
clicked = False
selected_effect = active_effect = 0 # PARTE DAL MUTO
write_mailbox = False


# INIZIALIZZAZIONE DELLE CLASSI

encoder = Encoder()
mailbox = mailbox_writer.Mailbox()
led = EffectLed(active=0)


MAILBOX_BASE = 0x2007C000



# CONFIGURO LA MAILBOX CON UNA CHIAMATA INIZIALE (IMPOSTA IL MUTO COME PRIMO EFFETTO)
mailbox.write(0, 0, 0, True)


# TEST: SINE GENERATOR WITH PWM
#sine_gen = SinePWM(7)

# TEST: PERIODIC PULSE
#pulse_gen = Impulse(7)

# TEST: SOFT PERIODIC PULSE
pulse_gen = SoftPulsePWM(7)

# ATTIVO TUTTI I VARI BLOCCHI NELL'ORDINE CORRETTO
# NOTA: A STO PUNTO MI CONVIENE LANCIARE TUTTE LE SEZIONI CRITICVHE DAL CORE 1

dsp.start_dsp()                         # AVVIA IL DSP 


# VERIFICA DELLA MEMORIA LIBERA/ALLOCATA
gc.collect()

print("GC allocati :", gc.mem_alloc())
print("GC liberi   :", gc.mem_free())
print("GC totale   :", gc.mem_alloc() + gc.mem_free())
print("\n")

pulse_gen.start()
#sine_gen.start()

# NUMERO DEGLI EFFETTI PER IL WRAP 
N_EFFECTS = 6


MAX_RECORDS = 512

try:
    time.sleep_ms(20)
    xsmt.value(1)       # SOFT MUTE DISATTIVATO

    adc0 = Read_ADC(26)
    adc1 = Read_ADC(27)

    last_value_p1 = adc0.read()         # RIVEDERE UN PO' STA PARTE, POTREBBE PORTARE A DEI GLITCH CON I POMELLI DURANTE L'INIZIALIZZAZIONE
    last_value_p2 = adc1.read()         # TIPO FLUTTUAZIONI INDESIDERATE

    pot_1_Q15 = last_value_p1 >> 1
    pot_2_Q15 = last_value_p2 >> 1


    print("\n\n V15 --- FORSE LA FINALE !!!! :)")

    while True:

        #write_mailbox = False

        # INIZIALMENTE LEGGO I NUOVI VALORI DEI POTENZIOMETRI / ENCODER
        pot_1_raw = adc0.read()
        pot_2_raw = adc1.read()

        # SEPARO LA LETTURA DEI SINGOLI POTENZIOMETRI E RISCRIVO SOLO UNA COSA ALLA VOLTA
        if pot_1_raw != last_value_p1:

            # AGGIORNO LA MEMORIA
            last_value_p1 = pot_1_raw

            # CONVERTO IN Q15
            pot_1_Q15 = pot_1_raw >> 1

            # AGGIORNO IL FLAG PER LA SCRITTURA
            write_mailbox = True

        # IDEM PER IL POTENZIOMETRO 2
        if pot_2_raw != last_value_p2:

            last_value_p2 = pot_2_raw
            pot_2_Q15 = pot_2_raw >> 1
            write_mailbox = True

        
        delta, clicked = encoder.read()

        # RIALLINEO SELEZIONE E LED (IL TIMER POTREBBE AVERLA DISALLINEATA)
        selected_effect = led.selected


        # MACCHINA A STATI UI, DECIDO COSA FARE IN BASE ALLE INTERAZIONI DELL'UTENTE
        # PRIMA COSA SE HO RUOTATO L'ENCODER DEVO ENTRARE NELLA FASE DI SELEZIONE DELL'EFFETTO
        if delta != 0:
            selected_effect = (selected_effect + delta) % N_EFFECTS       # ORA PUNTA L'EFFETTO SUCCESSIVO
            #next_effect = (selected_effect + 1) % N_EFFECTS

            led.select(selected_effect)


        # SECONDA COSA, DEVO RILEVARE LA PRESSIONE DEL TASTO PER USCIRE DALLA MODALIÀ DI SELEZIONE
        if clicked and (active_effect != selected_effect):

            # FASE CRITICA: FORZO MANUALMENTE IL PASSAGGIO DELL'EFFETTO CON LA SEQUENZA MUTO -> SLEEP -> NUOVO EFFETTO
            led.start_change()

            # PRIMO PASSO: MUTO, SERVE SOLO SE NON STO CERCANDO DI SELEZIONARE IL MUTO
            if active_effect != 0:
                mem32[MAILBOX_BASE + 0x0C] = 1
                mailbox.write(0, 0, 0, True)                                    # FORZA IL MUTO

                while(mem32[MAILBOX_BASE + 0x0C] != 0):                         # ASPETTO IL VIA LIBERA DAL DSP: USCITA MUTATA
                    time.sleep_ms(5)


            active_effect = selected_effect                                 # AGGIORNA LA MEMORIA

            # SECONDA FASE: NUOVO EFFETTO, SE IL TARGET È IL MUTO LA FASE 1 L'HA GIÀ CHIAMATO
            if active_effect != 0: 
                mem32[MAILBOX_BASE + 0x0C] = 1
                mailbox.write(active_effect, pot_1_Q15, pot_2_Q15, True)        # INIZIALIZZA IL NUOVO EFFETTO

                while(mem32[MAILBOX_BASE + 0x0C] != 256):
                    time.sleep_ms(5)

            led.set_active(active_effect)
            write_mailbox = False                                           # ANNULLA LA SCRITTURA DI QUESTO CICLO


            
            #for i in range (44):
            #    print(mem32[MAILBOX_BASE + i*4])


        # SCRITTURA DELLA MAILBOX IN RAM
        if write_mailbox:
            mailbox.write(active_effect, pot_1_Q15, pot_2_Q15, False)
            write_mailbox = False

        

        time.sleep_ms (20)  # SLEEP PRIMA DI RIPETERE IL CICLO

# Cattura il ^C
except KeyboardInterrupt:
    print("\n^C rilevato! Uscita dal programma...")

# Esegue il blocco una sola volta per disattivare le sm, timer e altre cose!
finally:

    mailbox.write(0, 0, 0, True)
    time.sleep_ms(500)
    xsmt.value(0)
    

    # ARRIVATI A QUESTO PUNTO POSSO FERMARE TUTTO, IL DAC HA GIÀ FATTO IL FADE OUT E AL MASSIMO STA CONTINUANDO A ELABORARE DEL SILENZIO IN RAM

    # Disattiva PWM:
    #sine_gen.stop()
    pulse_gen.stop()

    # DISATTIVA IL DSP
    dsp.stop_dsp()


    # STAMPA LE STATISTICHE
    #print("\n STATISTICHE DEI PRIMI ", MAX_RECORDS, " CICLI\n")

    for i in range(MAX_RECORDS):
        #print("TRASFERIMENTO DI UN BLOCCO (DMA RX): ", dma_rx_transfer_time[i])
    #    #print("DURATA GESTIONE DELL'INTERRUPT: ", irq_handler_time[i])
        print("DURATA ELABORAZIONE BLOCCO (DSP):", dsp.dsp_elaboration_time[i])
    
    print()

    #print("FLUSH TIME:")
    #for i in range (64):
    #    #print(dsp_test.lag_log[i])
    #    print(dsp.flush_time[i])

    # METTERE PER BENE

    scki = Pin(2, Pin.OUT)
    bck = Pin(3, Pin.OUT)
    lrck = Pin(4, Pin.OUT)
    dout = Pin(6, Pin.OUT)

    # Abbassa i segnali dei clock
    scki.value(0)
    bck.value(0)
    lrck.value(0)
    dout.value(0)
