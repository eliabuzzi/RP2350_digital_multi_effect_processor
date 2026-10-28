import math
import time
from machine import Pin, PWM, Timer

SINE_FREQ = 440
PWM_FREQ = 100_000
N_SAMPLES = 16
V_REF = 0x8000          # CENTRA L'ONDA A 1.65V
#AMPLITUDE = 0x6978      # LASCIA UN PO' DI MARGINE PER STARE DENTRO AGLI ABSOLUTE RATINGS
AMPLITUDE = 0x1F40

# COSTANTI PER L'IMPULSO "MORBIDO"
PULSE_STEPS = 10
PULSE_STEP_TIME = 500       # DURATA DI OGNI GRADINO
PULSE_AMP = AMPLITUDE       # AMPIEZZA MASSIMA DEL GRADINO




# GENERA UNA SINUSOIDE DIGITALE E RIEMPE UN BUFFER CON I SUOI CAMPIONI
def sine_buffer(buffer, sample_rate, frequency, amplitude):

    # Generazione del tono
    for i in range(len(buffer)):
        t = i / sample_rate
        buffer[i] = int(amplitude * math.sin(2 * math.pi * frequency * t))

# Genera un tono a 440Hz tramite la PWM del Raspberry
class SinePWM:

    # Costruttore, imposta la PWM sulla GPIO passata come argomento e inizializza frequenze, duty cicle e look up table
    def __init__(self, pwm_gpio: int):
        self.gpio = pwm_gpio
        self.pwm_sine = PWM(Pin(self.gpio))

        # Portante della PWM (100Khz)
        self.pwm_sine.freq(PWM_FREQ)

        # Frequenza del segnale fissata a 440Hz, uso 16 campioni per onda così resto leggero
        self.num_samples = N_SAMPLES

        # Frequenza del Timer software
        self.timer_freq = SINE_FREQ * self.num_samples

        # LOOK UP TABLE: 0x0000 = 0.0V, 0xFFFF = 3.3V, 0x8000 = 1.65V, Vmax~3V, Vmin~0.15V
        self.sine_table = []
        for i in range(self.num_samples):
            t = i / self.num_samples
            val = int(V_REF + AMPLITUDE * math.sin(2 * math.pi * t))
            self.sine_table.append(val)

        # Indice per scorrere i campioni
        self.index = 0

        # Timer virtuale
        self.timer = Timer(-1)

    # Callback del timer: aggiorna i valori del duty cicle e incrementa l'indice (con wrap)
    def update(self, timer):
        self.pwm_sine.duty_u16(self.sine_table[self.index])
        self.index = (self.index + 1) % self.num_samples

    # Avvia il timer
    def start(self):
        self.timer.init(freq=self.timer_freq, mode=Timer.PERIODIC, callback=self.update)
        print("Generatore PWM a 440Hz avviato sulla GPIO ", self.gpio)

    # Ferma il timer e lascia l'uscita fissa a 1.65V (evita che la tensione crolli a 0 bruscamente)
    def stop(self):
        self.timer.deinit()
        self.pwm_sine.duty_u16(V_REF)
        print("Generatore PWM fermato...")

# GENERA UN PICCOLO IMPULSINO
class Impulse:
    def __init__(self, gpio: int, period_ms: int = 500, pulse_us: int = 100):
        self.gpio = Pin(gpio, Pin.OUT,)
        self.gpio.value(0)
        self.period_ms = period_ms
        self.pulse_us = pulse_us
        self.timer = Timer(-1)

    # GENERA UN SINGOLO IMPULSO CHE DURA 100 us
    def pulse(self, timer=None):
        self.gpio.value(1)
        time.sleep_us(self.pulse_us)
        self.gpio.value(0)

    def start(self):
        self.timer.init(mode=Timer.PERIODIC, period=self.period_ms, callback=self.pulse)

    def stop(self):
        self.timer.deinit()
        self.gpio.value(0)

# GENERA UNA RAMPA PER TESTARE L'ECHO
class SoftPulsePWM:

    def __init__(self, pwm_gpio: int, period_ms: int = 1500, steps: int = PULSE_STEPS, step_time: int = PULSE_STEP_TIME, amplitude: int = PULSE_AMP):

        # INIZIALIZZAZIONE PWM
        self.gpio = pwm_gpio
        self.pwm = PWM(Pin(self.gpio))
        self.pwm.freq(PWM_FREQ)
        self.pwm.duty_u16(V_REF)            # PUNTO DI RIPOSO A 1.65V

        # INIZIALIZZAZIONE COSTANTI
        self.period_ms = period_ms
        self.steps = steps
        self.step_time = step_time
        self.amplitude = amplitude

        # PRECALCOLO I GRADINI DELLA RAMPA USANDO INTERI
        self.ramp = []
        step_val = self.amplitude // self.steps

        # GENERO I GRADINI IN SALITA (dalla V_REF al picco positivo)
        for i in range(self.steps):
            self.ramp.append(V_REF + (i * step_val))

        # GENERO I GRADINI IN DISCESA (dal picco alla V_REF)
        for i in range(self.steps, -1, -1):
            self.ramp.append(V_REF + (i * step_val))

        # INIZIALIZZO IL TIMER
        self.timer = Timer(-1)

    def pulse(self, timer=None):
        for value in self.ramp:
            self.pwm.duty_u16(value)
            time.sleep_us(self.step_time)

        # TORNA A CENTRARE IL SEGNALE SULLA V_REF
        self.pwm.duty_u16(V_REF)

    def start(self):
        self.timer.init(mode=Timer.PERIODIC, period=self.period_ms, callback=self.pulse)
        print("Soft Pulse attiva sulla GPIO ", self.gpio)

    def stop(self):
        self.timer.deinit()
        self.pwm.duty_u16(V_REF)