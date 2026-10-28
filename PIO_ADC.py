from machine import Pin
import rp2

#DMA_WORDS = 4096           # 4096*32 bit = 16 kByte
DMA_WORDS = 64             # INVIA UN IRQ ALLA CPU OGNI 256 PAROLE AUDIO, 
                            # NOTA: QUESTO NON INTERFERISCE CON IL WRAP DELL'INDIRIZZO DI SCRITTURA CHE VINENE GESTITO AUTONOMAMENTE DAL RING SIZE

# PARAMETRI CONFIGURAZIONE
FS = 48_000            
#BITS = 32

# FREQUENZE DI FUNZIONAMENTO
SYS_CLK = 144_000_000   #   144 Mhz -> Divisione frazionaria a 16 bit di mantissa gestita correttamente dal PLL frazionario (???)
PIO_CLK = 98_304_000    #   98.304 Mhz -> 32 istruzioni * BCK


LRCK = FS              # PCM INPUT CLOCK (FS) (1 frame stereo =  64 colpi BCK)         
BCK = 64 * FS          # BIT WORD CLOCK 
SCKI = 256 * FS        # CLOCK INTERNO FUNZIONAMENTO PCM (256*fs da specifiche TI)

# PIN GPIO PER INGRESSI/USCITE
SCKI_PIN = 2                        # MASTER CLOCK
BCK_PIN = 3                         # BIT CLOCK
LRCK_PIN = 4                        # WORD SELECT CLOCK
DIN_PIN = 5                         # DATA IN PIN (FROM ADC)
#DOUT_PIN = 6                        # DATA OUT PIN (TO DAC)

def pio_adc():
    global scki, bck, lrck
    
    # PRECAUZIONE!! ABILITARRE I PIN GPIO COME INGRESSI/USCITE
    scki = Pin(SCKI_PIN, Pin.OUT)
    bck = Pin(BCK_PIN, Pin.OUT)
    lrck = Pin(LRCK_PIN, Pin.OUT)
    din = Pin(DIN_PIN, Pin.IN)
    # dout = Pin(DOUT_PIN, Pin.OUT)     METTERE NEL DAC

    # PIO STATE MACHINE PER GENERARE I CLOCK

    # DECORATORE CLOCK
    @rp2.asm_pio(
        sideset_init=[
            rp2.PIO.OUT_LOW,    # bit 0: GPIO2 SCKI
            rp2.PIO.OUT_LOW,    # bit 1: GPIO3 BCK
            rp2.PIO.OUT_LOW     # bit 2: GPIO4 LRCK
        ],
        in_shiftdir=rp2.PIO.SHIFT_LEFT,
        autopush=True,
        push_thresh=32,  
        fifo_join=rp2.PIO.JOIN_RX
    )

    # INFO

    # Ogni istruzine ha [3] cicli di delay: 1 istruzione + 3 delay = 4 cicli PIO
    # Ogni state machine supporta fino a 32 operazioni per blocco PIO
    # Ogni ciclo dura T = [1/(98.304Mhz)], 4 cicli durano 4T = 40.69ns

    # VARIAZIONI DEI CLOCK: voglio questo comportamento:

    # SCKI: cambia ogni 4 cicli
    #   HIGH -> 4 cicli
    #   LOW  -> 4 cicli
    #   PERIODO: 8 cicli quindi Fscki = PIO_CLK / 8 (12.288 Mhz) -> ok fs*256

    # BCK: cambia ogni 16 cicli
    #   HIGH -> 16 cicli
    #   LOW  -> 16 CICLI
    #   PERIODO: 32 cicli quindi Fbck = PIO_CLK / 32 (3.072 Mhz) -> ok fs*64

    # LRCK: cambia ogni 32 cicli di BCK (32*32=1024) NOTA: sono 32 per audio_L e 32 per audio_R
    #   HIGH -> 1024 cicli
    #   LOW  -> 1024 cicli
    #   PERIODO: 2048 cicli quindi Flrck = PIO_CLK / 2048 (48 Khz) -> ok == fs

    # STATE MACHINE PER IL CLOCK
    def pcm_clocks():

        # SIDESET: LCRK|BCK|SCKI, 0 = LOW, 1 = HIGH

        set(x, 31).side(0b000) # CARICO I REGISTRI PRELIMINARIAMENTE
        set(y, 31).side(0b000)

        wrap_target() 

        # LRCK LOW (LEFT WORD), 32 CICLI BCK
        label("lrck_low")

        # BCK LOW, SCKI OSCILLA
        set(y, 31).side(0b000) [3]
        nop().side(0b001) [3]

        nop().side(0b000) [3]
        nop().side(0b001) [3]

        # BCK HIGH, IL DATO COMMUTA SUL FALLING EDGE PRECEDENTE, CAMPIONO SUL RISING EDGE
        in_(pins, 1).side(0b010) [3]
        #nop().side(0b010) [3]
        nop().side(0b011) [3]

        nop().side(0b010) [3]
        jmp(x_dec, "lrck_low").side(0b011) [3]


        # LRCK HIGH (RIGHT WORD), 32 CICLI BCK
        label("lrck_high")

        # BCK LOW, SCKI OSCILLA
        set(x, 31).side(0b100) [3]
        nop().side(0b101) [3]

        nop().side(0b100) [3]
        nop().side(0b101) [3]

        # BCK HIGH

        #in_(pins, 1).side(0b110) [3]
        nop().side(0b110) [3]
        nop().side(0b111) [3]

        nop().side(0b110) [3]

        jmp(y_dec, "lrck_high").side(0b111) [3]

        wrap()


    # INZIALIZZO SM1
    sm1 = rp2.StateMachine(0, pcm_clocks, freq=PIO_CLK, sideset_base=scki, in_base=din)

    return sm1