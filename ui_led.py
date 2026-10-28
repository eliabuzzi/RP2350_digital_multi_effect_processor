from machine import Pin, PWM, Timer
import time

class EffectLed:
    # COLORI (R, G, B) PER EFFETTO: 0 MUTE, 1 BYPASS, 2 REVERB, 3 DELAY, 4 BITCRUSHER, 5 FREQYENCY SHIFTER
    COLORS = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1))

    def __init__(self, pins=(11, 12, 13), timeout_ms=5000, level=15000, active=0):
        self.pwm = [PWM(Pin(p)) for p in pins]
        for p in self.pwm:
            p.freq(1000)

        self.level = level                  # LUMINOSITA' (0-65535), TENUTA BASSA PER NON ABBAGLIARE
        self.timeout_ms = timeout_ms
        self.active = active                # EFFETTO ATTIVO
        self.selected = active              # EFFETTO SELEZIONATO CON L'ENCODER
        self.touch = time.ticks_ms()        # ULTIMA VOLTA CHE HO TOCCATO L'ENCODER
        self.busy = False                   # True DURANTE IL CAMBIO EFFETTO (NIENTE TIMEOUT)

        # TIMER SOFTWARE A 50 ms: LA CALLBACK NON ALLOCA NULLA
        self.timer = Timer(period=50, mode=Timer.PERIODIC, callback=self._tick)

    def select(self, effect):
        # DA CHIAMARE QUANDO RUOTI L'ENCODER
        self.selected = effect
        self.touch = time.ticks_ms()

    def start_change(self):
        # DA CHIAMARE AL CLICK, PRIMA DELL'HANDSHAKE
        self.busy = True

    def set_active(self, effect):
        # DA CHIAMARE QUANDO IL FADE IN E' FINITO
        self.active = effect
        self.selected = effect
        self.busy = False

    def _tick(self, t):
        now = time.ticks_ms()
        pending = self.selected != self.active

        # TIMEOUT: SE NON TOCCO L'ENCODER PER 5 s, ANNULLO LA SELEZIONE
        if pending and not self.busy:
            if time.ticks_diff(now, self.touch) > self.timeout_ms:
                self.selected = self.active
                pending = False

        # LAMPEGGIO A CIRCA 2 Hz SOLO SE LA SELEZIONE E' PENDENTE
        off = pending and ((now >> 8) & 1)
        c = self.COLORS[self.selected]
        for i in range(3):
            self.pwm[i].duty_u16(self.level if (c[i] and not off) else 0)


#led = EffectLed(active=5)