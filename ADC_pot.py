from machine import ADC
import array
import time

# NOTA: ADC DEL PICO HA 12 BIT DI RISOLUZIONE MAPPATI IN UNA VARIABILE DA 16 BIT UNSIGNED, IL RANGE È 0 - 65535 (0xFFFF)

BITS = 5                        # NUMERO DI BIT PER LA MEDIA (2^5 LETTURE)
DEADBAND = 1024                  # SOGLIA DEL RUMORE DA IGNORARE
EDGE_MARGIN = 256              # FORZA GLI ESTREMI AI VALORI MINIMI E MASSIMI

# NOTA: TENERE MARGIN <= DEADBAND // 4 PER EVITARE SFARFALLAMENTI AGLI ESTREMI

ADC_MIN = 0x0000
ADC_MID = 0x7FFF
ADC_MAX = 0xFFFF


class Read_ADC:

    def __init__(self, gpio_adc, deadband=DEADBAND, margin=EDGE_MARGIN, avg_bits=BITS):
        self.adc = ADC(gpio_adc)
        self.deadband = deadband
        self.margin = margin
        self.top = ADC_MAX - margin
        self.avg_bits = avg_bits
        self.last_value = -65536            # LA PRIMA READ VIENE SEMPRE ACCETTATA
        self.read()

    def read(self):
        #raw_value = self.adc.read_u16()

        acc = 0

        # PER DEBUG
        #t0 = time.ticks_us()

        # OVERSAMPLING
        for _ in range(32):
            acc += self.adc.read_u16()

        raw_value = acc >> self.avg_bits

        #t_elapsed = time.ticks_diff(time.ticks_us(), t0)
        #print("Tempo per il ciclo di oversampling (us): ", t_elapsed)
    
        # CLAMP DEI MARGINI
        if raw_value < self.margin:
            raw_value = 0
        elif raw_value > self.top:
            raw_value = ADC_MAX - 2000

        last_value = self.last_value

        # ISTERESI
        if raw_value == 0 or raw_value == 65535 or raw_value > last_value + self.deadband or raw_value < last_value - self.deadband:
            self.last_value = raw_value
            return raw_value
        
        return last_value

#adc = Read_ADC(26)
#
#aux = array.array('i', [0] * 1000) 
#
##for i in range(10):
##    print(adc.read())
#
#for i in range (1000):
#    aux[i] = adc.read()
#    #time.sleep_ms(20)
#
#for i in range (1000):
#    print(aux[i])