from machine import Pin
import time

# CLASSE PER LA GESTIONE DELL'ENCODER ROTATIVO (DELTA E CLICKED), RITORNERÀ UN VALORE PER LA POSIZIONE DELLA MANOVELLA
# E UN FLAG PER LA SELEZIONE DELL'EFFETTO (CLICCATO OPPURE NO)

class Encoder:

    def __init__(self, gpio_clk=10, gpio_dt=9, gpio_sw=8, debounce_ms = 30):

        # CONFIGURAZIONE PIN
        self.pin_clk = Pin (gpio_clk, Pin.IN)
        self.pin_dt = Pin (gpio_dt, Pin.IN)
        self.pin_sw = Pin (gpio_sw, Pin.IN, Pin.PULL_UP)        # PULL UP DI SICUREZZA SUL TASTO

        self.debounce_ms = debounce_ms

        # CONFIGURAZIONE MEMORIE DEGLI STATI PRECEDENTI
        self.last_value_clk = self.pin_clk.value()
        self.last_value_sw = self.pin_sw.value()
        self.last_clicked = time.ticks_ms()

    def read(self):

        # LEGGE L'ENCODER A OGNI CICLO RITORNANDO UNA TUPLA (DELTA, CLICKED)
        # NOTA: DELTA -> +1 (ORARIO), -1 (ANTIORARIO), 0 (FERMO)

        t0 = time.ticks_ms()
        delta = 0
        clicked = False

        clk = self.pin_clk.value()
        dt = self.pin_dt.value()
        sw = self.pin_sw.value()

        # LETTURA ROTAZIONE: RILEVO IL FRONTE DI DISCESA DI CLK
        if clk == 0 and self.last_value_clk == 1:
            if dt == 1:
                delta = 1       # SENSO ORARIO
            else:
                delta = -1      # SENSO ANTIORARIO

        self.last_value_clk = clk       # AGGIORNO LA MEMORIA

        # LETTURA DEL PULSANTE: CONTROLLO IL FRONTE DI DISCESA DI SW
        if sw == 0 and self.last_value_sw == 1:

            # DEBOUNCE TEMPORALE
            if time.ticks_diff(t0, self.last_clicked) > self.debounce_ms:
                clicked = True
                self.last_clicked = t0

        self.last_value_sw = sw

        return delta, clicked

#encoder = Encoder()

#while True:
#    delta, clicked = encoder.read()

#    print("Delta: ", delta)
#    print("Cliccato: ", clicked, "\n")

#    time.sleep_ms(20)