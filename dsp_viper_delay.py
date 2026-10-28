import array
import micropython

# CODICE VIPER PER IMPLEMENTARE UN TAPE DELAY (ECHO DUB)

# STRUTTURA DEL BUFFER (array 'h):
# 32 half word di header (16 word da 32 bit)
# 0: indice scrittura, 1: memoria passa basso, 2: versione locale, 3: time target (campioni)
# 4 feedback targer (q15), 5: time current (q4), 6: feedback current (<<10)
# poi 2^15 campioni di delay line 
# HP E DC BLOCK: hp_in (7), hp_out (8), dc_in (9), dc_out(10)
# LP ECHO: lp_in (11), lp_out(12) --> IN REALTÀ È UN HP CHE SI SPOSTA (??)

# LUNGHEZZA TOTALE 0x8010

# PARAMETRI: [0] = POT_1 (Q15) - TEMPO, [1] = POT_2 (Q15) - FEEDBACK

#delay_buffer = array.array('h', [0] * BUFFER_LENGHT)

@micropython.viper

# AGGIUNGERE HP E DC BLOCK (4 MEMORIE AGGIUNTIVE, AUMENTARE HEADER A 16 WORD 32 BIT)?

def dsp_viper_delay(block_index: int, global_version: int, parameters_addr: int, memory_buffer: ptr16):
    # VARIABILI LOCALI MAPPATE NEI REGISTRI DI VIPER

    BASE_IN = ptr32(0x2006C000)
    BASE_OUT = ptr32(0x20074000)

    # DA QUI
    state = ptr32(memory_buffer)                # CASTO IL BUFFER ANCHE COME PTR32 PER LEGGERE LE WORD DELLO STATO
    parameters = ptr32(parameters_addr)

    block_size = 64

    offset = block_index * block_size

    # COSTANTI 
    DELAY_MASK = 0x8000 - 1             # MASCHERA BITWISE PER IL WRAP
    DELAY_BASE = 0x20                   # OFFSET PER IL DELAY BUFFER (LE PRIME 16 HALF WORD SONO DI HEADER)
    DAMP = 13107                      # 0.4 in Q15, FISSO
    TIME_MIN = 480                      # 10 ms A 48KHz
    TIME_RANGE = 31520                  # TEMPO MASSIMO: 32000 CAMPIONI (~0.67s)
    FB_MAX = 29491                      # 0.90 in Q15
    MAX_STEP = 2                        # VELOCITÀ MASSIMA DELLA RAMPA (1/16 DI CAMPIONE PER UNITÀ)
    DEADBAND = 1024

    local_version = int(state[2])

    # AGGIORNO I PARAMETRI CON LA LETTURA DELLA MAILBOX SOLO SE LE VERSIONI NON COINCIDONO
    if local_version != global_version:

        pot_1 = int(parameters[0])
        pot_2 = int(parameters[1])

        time_target = TIME_MIN + ((pot_1 * TIME_RANGE) >> 15)
        feedback_target = (pot_2 * FB_MAX) >> 15

        # AGGIORNO I PARAMETRI NELLA MEMORIA
        state[2] = global_version
        state[3] = time_target
        state[4] = feedback_target

    else:       # LEGGO I TARGET DALLE MEMORIE (NON SONO CAMBIATI)

        time_target = int(state[3])
        feedback_target = int(state[4])

    time_current = int(state[5])
    feedback_current = int(state[6])

    # PRIMO BLOCCO DOPO IL FLUSH: INIZIALIZZO DIRETTAMENTE I TARGET SENZA RAMPA
    if time_current == 0:
        time_current = time_target << 4
        feedback_current = feedback_target << 10
    
    # NOTA: POI FARÒ CHE IL DELAY SI MODIFICHI IN REAL TIME GRAZIE AL CORE 0 PER FARE GLI EFFETTI DI WARP (SPIRAL)

    # FILTRI HP E DC BLOCK
    hp_in = int(state[7])
    hp_out = int(state[8])

    dc_in = int(state[9])
    dc_out = int(state[10])

    hp_fb_in = int(state[11])
    hp_fb_out = int(state[12])

    # ELABORAZIONE
    for i in range(block_size):
        # LETTURA CAMPIONE E NORMALIZZAZIONE
        global_index = offset + i
        sample_raw = int(BASE_IN[global_index])

        # SHIFTO PER RIMUOVERE LA TRAMA I2S DAL CAMPIONE AUDIO
        sample_16 = (sample_raw << 1) >> 16

        # FILTRO PASSA ALTO
        hp = sample_16 - hp_in + ((hp_out * 16319 + 0x2000) >> 14)

        hp_in = sample_16
        hp_out = hp

        sample_16 = hp

        sample_16_att = sample_16 >> 1            # VERSIONE ATTENUATA DI 1 BIT PER EVITARE CHE IL SOMMATORE SATURI SUBITO

        # SMOOTHING DEL TEMPO: RAMPA LINEARE PER EFFETTO NASTRO
        time_difference = (time_target << 4) - time_current
        if time_difference > MAX_STEP:
            time_current += MAX_STEP
        elif time_difference < -MAX_STEP:
            time_current -= MAX_STEP
        else:
            time_current = time_target << 4

        frac_register = time_current & 15                    # PARTE FRAZIONARIA (4 BIT LSB)

        delay_time = time_current >> 4

        # SMOOTHING DEL FEEDBACK (ESPONENZIALE COME NEL RIVERBERO)
        feedback_difference = (feedback_target << 10) - feedback_current
        if feedback_difference > DEADBAND or feedback_difference < -DEADBAND:
            feedback_current += (feedback_difference >> 10)
        else:
            feedback_current = (feedback_target << 10)

        feedback = feedback_current >> 10


        # TAPE DELAY - ECHO DUB, VERSIONE INTERPOLATA

        w_index = int(state[0])                     # INDICE DI SCRITTURA
        #r_index = (w_index - delay_time) & DELAY_MASK       # INDICE DI LETTURA (CAMPIONE RITARDATO)

        r0_index = (w_index - delay_time) & DELAY_MASK
        r1_index = (r0_index - 1) & DELAY_MASK

        sample_0 = (int(memory_buffer[DELAY_BASE + r0_index]) << 16) >> 16  # LETTURE CON ESTENSIONE MANUALE DEL SEGNO
        sample_1 = (int(memory_buffer[DELAY_BASE +  r1_index]) << 16) >> 16

        # INTERPOLAZIONE LINEARE
        out_buf = sample_0 + (((sample_1 - sample_0) * frac_register + 8) >> 4)

        #out_buf = int(memory_buffer[DELAY_BASE + r_index]) 
        #out_buf = (out_buf << 16) >> 16                         # ESTENSIONE MANUALE DEL SEGNO, ptr16 LEGGE SEMPRE UNSIGNED

        # PASSA BASSO IIR (1 POLO)
        prev_state = int(state[1])
        new_state = (out_buf * (0x8000 - DAMP) + prev_state * DAMP + 0x4000) >> 15
        state[1] = new_state

        # PASSA ALTO PER IL FEEDBACK
        fb_hp = new_state - hp_fb_in + ((hp_fb_out * 16170 + 0x2000) >> 14)
        hp_fb_in = new_state
        hp_fb_out = fb_hp

        new_state = fb_hp

        # ACCUMULATORE 
        accum = sample_16_att + ((new_state * feedback + 0x4000) >> 15)

        # SOFT CLIPPER A SOGLIE MULTIPLE: SIMULA LA SATURAZIONE ANALOGICA
        # OLTRE LA METÀ DELLA SCALA, IL LIVELLO SI DIMEZZA, SUPERATA ANCORA LA METÀ SI DIMEZZA ANCORA

        if accum > 16384:
            accum = 16384 + ((accum - 16384 + 1) >> 1)
            if accum > 24576:
                accum = 24576 + ((accum - 24576 + 1) >> 1)
            if accum > 32767:
                accum = 32767

        if accum < -16384:
            accum = -16384 + ((accum + 16384 + 1) >> 1)
            if accum < -24576:
                accum = -24576 + ((accum + 24576 + 1) >> 1)
            if accum < -32768:
                accum = -32768 

        # AGGIORNAMENTO DELLA MEMORIA CAMPIONI
        memory_buffer[DELAY_BASE + w_index] = accum
        state[0] = (w_index + 1) & DELAY_MASK

        y = new_state

        # BLOCCO DC
        out = y - dc_in + ((dc_out * 16350 + 0x2000) >> 14)
        dc_in = y
        dc_out = out

        y = out                     # EVENTUALMENTE QUI POSSO RECUPERARE UN BIT DI GUADAGNO PERSO PRIMA

        # CLIPPING
        if y > 32767:
            y = 32767
        elif y < -32768:
            y = -32768


        # SCRITTURA DELL'USCITA
        BASE_OUT[global_index] = (y << 15)

    state[5] = time_current
    state[6] = feedback_current

    state[7] = hp_in
    state[8] = hp_out

    state[9] = dc_in
    state[10] = dc_out

    state[11] = hp_fb_in
    state[12] = hp_fb_out