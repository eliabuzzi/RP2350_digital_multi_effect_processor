import micropython

# BODE FREQUENCY SHIFTER (SSB) - USCITA 100% WET
# STRUTTURA DEL BUFFER (array 'i', 2112 WORD):
# 0: LOCAL VERSION, 1: INC TARGET, 2: FEEDBACK TARGET (Q15), 3: PHASE, 4: INC CURRENT,
# 5: FEEDBACK CURRENT (<<10), 6: CAMPIONE DI FEEDBACK, 7: RITARDO 1 CAMPIONE (RAMO I)
# 8-9: HP1 (IN, OUT), 10-11: HP2 (IN, OUT), 12-13: LP1, LP2, 14-15: DC BLOCK (IN, OUT)
# 16-47: ALL PASS (8 SEZIONI x 4 WORD: [X_PARI, Y_PARI, X_DISPARI, Y_DISPARI])
# 48-63: LIBERE
# 64-2111: SINE TABLE (2048 PUNTI, Q15)
# PARAMETRI: [0] = POT_1 (SHIFT, ZERO AL CENTRO), [1] = POT_2 (FEEDBACK)

@micropython.viper

def dsp_viper_frequency_shifter(block_index: int, global_version: int, parameters_addr: int, memory_buffer: ptr32):

    BASE_IN = ptr32(0x2006C000)
    BASE_OUT = ptr32(0x20074000)

    parameters = ptr32(parameters_addr)

    block_size = 64
    offset = block_index * block_size

    # COSTANTI
    SINE_BASE = 64
    DEAD_ZONE = 300             # ZONA MORTA DEL POT_1 INTORNO AL CENTRO
    UP_K = 111                  # CURVA QUADRATICA: MASSIMO CIRCA +2500 Hz
    DOWN_K = 67                 # CURVA QUADRATICA: MASSIMO CIRCA -1500 Hz
    FB_MAX = 29491              # 0.90 IN Q15
    DEADBAND = 1024
    HP_A = 16171                # 2 STADI DA ~100 Hz -> -3 dB COMBINATO CIRCA 155 Hz (Q14)
    LP_A = 28460                # 2 STADI, -3 dB COMBINATO CIRCA 10 kHz (Q15)
    DC_A = 16350                # BLOCCO DC IN USCITA, CIRCA 16 Hz (Q14)
    OUT_THRESH = 24000

    # AGGIORNAMENTO PARAMETRI (SOLO SE LA VERSIONE È CAMBIATA)
    local_version = int(memory_buffer[0])

    if local_version != global_version:

        pot_1 = int(parameters[0])
        pot_2 = int(parameters[1])

        d = pot_1 - 16384
        if d > DEAD_ZONE:
            d -= DEAD_ZONE
            inc_target = ((d * d) >> 7) * UP_K              # INCREMENTO DI FASE = Hz * 89478
        elif d < -DEAD_ZONE:
            d += DEAD_ZONE
            inc_target = -(((d * d) >> 7) * DOWN_K)
        else:
            inc_target = 0

        feedback_target = (pot_2 * FB_MAX) >> 15

        memory_buffer[0] = global_version
        memory_buffer[1] = inc_target
        memory_buffer[2] = feedback_target

    else:
        inc_target = int(memory_buffer[1])
        feedback_target = int(memory_buffer[2])

    # CARICO GLI STATI
    phase = int(memory_buffer[3])
    inc_current = int(memory_buffer[4])
    feedback_current = int(memory_buffer[5])
    fb_sample = int(memory_buffer[6])
    hil_delay = int(memory_buffer[7])
    hp1_in = int(memory_buffer[8])
    hp1_out = int(memory_buffer[9])
    hp2_in = int(memory_buffer[10])
    hp2_out = int(memory_buffer[11])
    lp1 = int(memory_buffer[12])
    lp2 = int(memory_buffer[13])
    dc_in = int(memory_buffer[14])
    dc_out = int(memory_buffer[15])

    # ELABORAZIONE
    for i in range(block_size):
        global_index = offset + i
        sample_raw = int(BASE_IN[global_index])

        # RIMOZIONE DELLA TRAMA I2S
        sample_16 = (sample_raw << 1) >> 16

        # PARITÀ DEL CAMPIONE: SELEZIONA LA COPPIA DI STATI DEGLI ALL PASS (0 O 2)
        par = (global_index & 1) << 1

        # PARAMETER SMOOTHING (INCREMENTO DI FASE E FEEDBACK)
        inc_difference = inc_target - inc_current
        if inc_difference > DEADBAND or inc_difference < -DEADBAND:
            inc_current += (inc_difference >> 10)
        else:
            inc_current = inc_target

        feedback_difference = (feedback_target << 10) - feedback_current
        if feedback_difference > DEADBAND or feedback_difference < -DEADBAND:
            feedback_current += (feedback_difference >> 10)
        else:
            feedback_current = (feedback_target << 10)

        feedback = feedback_current >> 10

        # INGRESSO + FEEDBACK, POI DOPPIO PASSA ALTO (CHIUDE ANCHE IL LOOP)
        x = sample_16 + fb_sample

        hp1 = x - hp1_in + ((hp1_out * HP_A + 0x2000) >> 14)
        hp1_in = x
        hp1_out = hp1

        hp2 = hp1 - hp2_in + ((hp2_out * HP_A + 0x2000) >> 14)
        hp2_in = hp1
        hp2_out = hp2

        x = hp2

        # CLAMP DI SICUREZZA E HEADROOM PER GLI ALL PASS (CON ARROTONDAMENTO)
        if x > 32767:
            x = 32767
        elif x < -32768:
            x = -32768

        x = (x + 2) >> 2

        # ---------------- RAMO I (INGRESSO RITARDATO DI 1 CAMPIONE) ----------------
        v = hil_delay
        hil_delay = x

        # I0: a = 0.6924 -> a^2 = 15709
        x_prev = int(memory_buffer[16 + par])
        y_prev = int(memory_buffer[17 + par])
        p = (v + y_prev) * 15709
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[16 + par] = v
        memory_buffer[17 + par] = y
        v = y

        # I1: a = 0.9361 -> a^2 = 28712
        x_prev = int(memory_buffer[20 + par])
        y_prev = int(memory_buffer[21 + par])
        p = (v + y_prev) * 28712
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[20 + par] = v
        memory_buffer[21 + par] = y
        v = y

        # I2: a = 0.9882 -> a^2 = 32001
        x_prev = int(memory_buffer[24 + par])
        y_prev = int(memory_buffer[25 + par])
        p = (v + y_prev) * 32001
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[24 + par] = v
        memory_buffer[25 + par] = y
        v = y

        # I3: a = 0.9987 -> a^2 = 32686
        x_prev = int(memory_buffer[28 + par])
        y_prev = int(memory_buffer[29 + par])
        p = (v + y_prev) * 32686
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[28 + par] = v
        memory_buffer[29 + par] = y
        i_out = y

        # ---------------- RAMO Q ----------------
        v = x

        # Q0: a = 0.4022 -> a^2 = 5301
        x_prev = int(memory_buffer[32 + par])
        y_prev = int(memory_buffer[33 + par])
        p = (v + y_prev) * 5301
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[32 + par] = v
        memory_buffer[33 + par] = y
        v = y

        # Q1: a = 0.8562 -> a^2 = 24020
        x_prev = int(memory_buffer[36 + par])
        y_prev = int(memory_buffer[37 + par])
        p = (v + y_prev) * 24020
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[36 + par] = v
        memory_buffer[37 + par] = y
        v = y

        # Q2: a = 0.9723 -> a^2 = 30977
        x_prev = int(memory_buffer[40 + par])
        y_prev = int(memory_buffer[41 + par])
        p = (v + y_prev) * 30977
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[40 + par] = v
        memory_buffer[41 + par] = y
        v = y

        # Q3: a = 0.9953 -> a^2 = 32460
        x_prev = int(memory_buffer[44 + par])
        y_prev = int(memory_buffer[45 + par])
        p = (v + y_prev) * 32460
        y = ((p + ((p >> 31) & 0x7FFF)) >> 15) - x_prev
        memory_buffer[44 + par] = v
        memory_buffer[45 + par] = y
        q_out = y

        # ---------------- NCO + MODULATORE SSB ----------------
        idx = (phase >> 21) & 2047                      # MASCHERA OBBLIGATORIA: LO SHIFT DI UN NEGATIVO È ARITMETICO
        sin_val = int(memory_buffer[SINE_BASE + idx])
        cos_val = int(memory_buffer[SINE_BASE + ((idx + 512) & 2047)])
        phase += inc_current                            # IL WRAP A 32 BIT È VOLUTO

        # SEGNO VERIFICATO IN SIMULAZIONE: I*COS + Q*SIN = UP SHIFT CON INCREMENTO POSITIVO
        ssb = ((i_out * cos_val + 0x4000) >> 15) + ((q_out * sin_val + 0x4000) >> 15)

        # ---------------- PASSA BASSO A 2 POLI ----------------
        lp1 += ((ssb - lp1) * LP_A + 0x4000) >> 15
        lp2 += ((lp1 - lp2) * LP_A + 0x4000) >> 15

        # MAKE-UP (COMPENSA LO >> 2 IN INGRESSO) E SOFT KNEE 8:1
        y = lp2 << 2

        if y > OUT_THRESH:
            y = OUT_THRESH + ((y - OUT_THRESH + 4) >> 3)
        elif y < -OUT_THRESH:
            y = -OUT_THRESH + ((y + OUT_THRESH + 4) >> 3)

        # FEEDBACK: PRELEVATO DOPO IL LIMITATORE, PRIMA DEL BLOCCO DC
        fb_sample = (y * feedback + 0x4000) >> 15

        # BLOCCO DC IN USCITA
        out = y - dc_in + ((dc_out * DC_A + 0x2000) >> 14)
        dc_in = y
        dc_out = out

        y = out

        # CLAMP DURO A 16 BIT
        if y > 32767:
            y = 32767
        elif y < -32768:
            y = -32768

        BASE_OUT[global_index] = (y << 15)

    # SALVATAGGIO DELLO STATO
    memory_buffer[3] = phase
    memory_buffer[4] = inc_current
    memory_buffer[5] = feedback_current
    memory_buffer[6] = fb_sample
    memory_buffer[7] = hil_delay
    memory_buffer[8] = hp1_in
    memory_buffer[9] = hp1_out
    memory_buffer[10] = hp2_in
    memory_buffer[11] = hp2_out
    memory_buffer[12] = lp1
    memory_buffer[13] = lp2
    memory_buffer[14] = dc_in
    memory_buffer[15] = dc_out