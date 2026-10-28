import rp2
from machine import Pin

# PIN GPIO PER INGRESSI/USCITE
SCKI_PIN = 2                        # MASTER CLOCK
BCK_PIN = 3                         # BIT CLOCK
LRCK_PIN = 4                        # WORD SELECT CLOCK
#DIN_PIN = 5                         # DATA IN PIN (FROM ADC)
DOUT_PIN = 6                        # DATA OUT PIN (TO DAC)



# PARAMETRI CONFIGURAZIONE
FS = 48_000            
#BITS = 32

# FREQUENZE DI FUNZIONAMENTO
SYS_CLK = 144_000_000   #   144 Mhz -> Divisione frazionaria a 16 bit di mantissa gestita correttamente dal PLL frazionario
PIO_CLK = 98_304_000    #   98.304 Mhz -> 32 istruzioni * BCK


# PIO PER L'INVIO DEI DATI AL DAC
def pio_dac():

    # INIZIALIZZO IL PIN PER L'USCITA
    dout = Pin(DOUT_PIN, Pin.OUT)

# DECORATORE RICEVENTE

    @rp2.asm_pio(
        out_init=rp2.PIO.OUT_LOW,           # INIZIALIZZA IL PIN DEI DATI COME USCITA    
        out_shiftdir=rp2.PIO.SHIFT_LEFT,    # INVIA PRIMA MSB (bit 31, 30, 29 ... 0)
        autopull=False,                     # NON FARE AUTOPULL (SERVE A GESTIRE MONO -> STEREO)
        
        # QUANDO L'OSR (OUTPUT-SHIFT-REGISTER) SI SVUOTA, LA PIO PESCA AUTOMATICAMENTE UNA PAROLA DALLA FIFO TX HW
        pull_thresh=32,                     # 32 bit di parola audio (1 parola = 32 cicli BCK per left e idem per right)
        fifo_join=rp2.PIO.JOIN_TX           # UNISCE LA FIFO DI RICEZIONE PER CREARNE UNA UNICA UNIDIREZIONALE MA CON IL DOPPIO DELLA CAPACITA'
    )

    # V2, DALL'ADC CAMPIONO IN MONO, QUA SALVO LA PAROLA MONO E LA TRASMETTO IN STEREO (O POTREI TRASMETTERE ZERI)

    def i2s_dac_tx(bck=BCK_PIN,lrck=LRCK_PIN): # NOTA: POSSO MANDARE LE PAROLE AUDIO DA 24 BIT ANCHE IN TRAME DA 32, IL PCM SE LO GESTISCE CORRETTAMENTE DA SOLO

        # NELLO STANDARD I2S L'USCITA DATI COMMUTA SUL FRONTE DI DISCESA DEL BCK, QUESTO PERMETTE DI AVERE UN DATO STABILE QUANDO IL DAC LO ANDRÀ A INTERPOLARE SUL FRONTE DI SALITA
        # IL DUMMY-BIT, COSÌ COME IL PADDING, VENGONO TRASMESSI SENZA PROBLEMI

        # ATTENDO DI AGGANCIARMI ALL'INIZIO DELLA TRAMA (SALTANDO LE PRIME DUE), AGGIUNGE UN PO' DI LATENZA MA MI PERMETTE DI AVERE UNA SINCRONIZZAZIONE CORRETTA E DI
        # NON "CADERE" ALL'INTERNO DI UNA PAROLA GIÀ IN TRASMISSIONE

        # ATTENDO LRCK LOW (CANALE SINISTRO) PER GARANTIRE UNA CORRETTA SINCRONIZZAZIONE

        #nop() [1]               # I PRIMI DUE CICLI COMPENSANO L'INIZIALIZZAZIONE DELLA SM PER I CLOCK
        wait(1, gpio, lrck)

        wrap_target()
        
        wait(0, gpio, lrck)     # WAIT FOR LRCK LOW (INIZIO TRAMA LEFT)
        
        set(x, 31)              # REGISTRO PER IL LOOP DA 32 CICLI

        pull(block)             # PESCA UN BLOCCO DA 32 BIT (PAROLA AUDIO MONO) DALLA FIFO
        mov(y, osr)             # SALVA UNA COPIA DEL CAMPIONE SINISTRO DA RISPEDIRE NEL DESTRO

        label("lrck_low")       # LABEL PER IL LOOP

        wait(0, gpio, bck)      # WAIT FOR BCK LOW (COSÌ SUL RISING EDGE SUCCESSIVO IL DATO È STABILE)

        out(pins, 1)            # MANDA 1 BIT DELL'OSR IN USCITA SUL PIN PASSATO COME BASE

        wait(1, gpio, bck)      # WAIT FOR BCK HIGH, COMPLETA IL CICLO PER LA TRASMISSIONE DI 1 BIT

        jmp(x_dec, "lrck_low")  # SALTO CONDIZIONATO

        # ATTENDO LRCK HIGH (CANALE DESTRO)

        wait(1, gpio, lrck)     # SINCRONIZZA SUL CANALE DESTRO

        set(x, 31)              # LOOP DA 32 CICLI

        mov(osr, y)             # RICARICA LO STESSO CAMPIONE MONO NELL'OSR

        label("lrck_high")

        wait(0, gpio, bck)

        out(pins, 1)

        wait (1, gpio, bck)

        jmp(x_dec, "lrck_high")

        wrap()

    # INIZIALIZZO SM2       OUT: PIN 6 (DOUT), la forzo sul blocco PIO2 per avere altre 32 istruzioni di memoria libere
    sm2 = rp2.StateMachine(4, i2s_dac_tx, freq=PIO_CLK, out_base=dout)#, in_base=bck) # 3 -> BCK, 4 -> LRCK, 6 -> DOUT
    # NOTA: BASE=BCK, OFFSET: 0 PER BCK, 1 PER LRCK

    return sm2