import micropython
import array

# CODICE VIPER PER IMPLEMENTARE FREEVERB

# ALLOCAZIONE PER IL BUFFER DELLE DELAY LINES:
# STRUTTURA: 8 FILTRI COMB CON DELAY MASSIMO DI 1760 CAMPIONI (LA POTENZA DI 2 PIÙ VICINA È 2048)
#            4 FILTRI ALL PASS CON DELAY MASSIMO DI 605 CAMPIONI, LA PRIMA POTENZA DI DUE È 1024
#            32 WORD PER L'HEADER DI STATO: 8 PER GLI INDICI DEI COMB, 8 PER LE MEMORIE PASSA-BASSO E 4 PER GLI ALL PASS (+12 DI PADDING)

# NOTA: AGGIUNTE ALTRE WORD NEL PADDING DELL'HEADER, IN SEQUENZA:
# LOCAL VERSION, P1_TARGET_Q15, P2_TARGET_Q15, P1_CURRENT_Q25, P2_CURRENT_Q25

# NUOVA VERSIONE: AGGIUNTE ALTRE WORD PER HP SULL'USCITA
# HP_IN (25), HP_OUT (26)
# E PER IL BLOCCO DC
# DC_IN (27), DC_OUT (28)

# AGGIUNTO PURE UN SOFT KNEE (WAVESHAPER A MEMORIA ZERO)
# LA SOGLIA DI INTERVENTO (20000) È IL 61% DELLA SCALA TOTALE (0 / 32767)


# NOTA: FIXED POINT Q15 -> 2^15 = 32768 = 0x8000
# DAMP = 0.2 * 0x8000

# PARAMETRI RIVERBERO
#damp = int(0x8000 * 0.2)
#feedback = int((0.8 * 0.28 + 0.7) * 0x8000)



#BUFFER_LENGTH = 0x5020 #(20512 = 8*2048 + 4*1024 + 32)

#delay_buffer = array.array('i', [0] * BUFFER_LENGTH)
#delay_buffer_address = uctypes.addressof(delay_buffer)

@micropython.viper

def dsp_viper_reverb(block_index: int, global_version: int, parameters_addr: int, memory_buffer: ptr32):
#   NOTA: METTO TUTTI I PARAMETRI COME VARIABILI LOCALI COSÌ VIPER LI MAPPA DIRETTAMENTE NEI REGISTRI

    # BASI PER LA LETTURA / SCRITTURA DEI VALORI
    BASE_IN = ptr32(0x2006C000)
    BASE_OUT = ptr32(0x20074000)

    parameters = ptr32(parameters_addr)

    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # NOTA: RICORDARSI DI FARE SEMPRE IL CAST A int() QUANDO DEVO LEGGERE DA PTR32 ALTRIMENTI MI VIENE RITORNATO UN UNSIGNED 
    # E QUANDO VADO A FARCI LE ELABORAZIONI SUCCEDE UN DISASTRO...
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # CONFRONTO LE VERSIONI PER VEDERE SE DEVO AGGIORNARE I PARAMETRI (EVITA DI LEGGERE LA MAILBOX INUTILMENTE SE NON CI SONO MODIFICHE, PROBLEMI DI CONCORRENZA)
    local_version = int(memory_buffer[20])

    if local_version != global_version:
            
            damp_target     =   int(parameters[0])
            feedback_target =   int(parameters[1])

            # SALVO SUBITO GLI AGGIORNAMENTI PER LE CHIAMATE SUCCESSIVE
            memory_buffer[20] = global_version
            memory_buffer[21] = damp_target
            memory_buffer[22] = feedback_target
    
    else:   # SE NON CI SONO MODIFICHE LEGGO QUELLI LOCALI
         
         damp_target        =   int(memory_buffer[21])
         feedback_target    =   int(memory_buffer[22])

    # LEGGO I VALORI DALLA MEMORIA (PER IL PARAMETER SMOOTHING)
    damp_current = int(memory_buffer[23])
    feedback_current = int(memory_buffer[24])

    # VEDERE SE USARE CONST O COSA
    block_size = 64

    # RESTERÀ DA VEDERE COME OTTIMIZZARE LE ISTRUZIONI (TIPO offset = block_index << block_size_bit)

    offset = block_index * block_size

    # ATTENZIONE !!! FLOAT IN VIPER SONO MEGA ILLEGALI, PASSARE DEI VALORI GIÀ CALCOLATI

    # VEDERE ANCHE SE CONVIENE PASSARE IL BUFFER COME PTR 32 O PASSARE IL SUO INDIRIZZO (ADDRESSOF)

    # MASCHERE BITWISE PER IL WRAP
    COMB_MASK = 0x800 - 1     #(2047)
    ALLPASS_MASK = 0x400 - 1  #(1023)

    # OFFSET PER IL DELAY BUFFER
    COMB_BASE = 0x20            # 32
    COMB_OFFSET = 0x800
    ALLPASS_BASE = COMB_BASE + 0x4000    # 32 + 8*2048
    ALLPASS_OFFSET = 0x400

    # DEADBAND PER IL PARAMETER SMOOTHING
    DEADBAND = 1024        # 1024 (2^10)

    # THRESHOLD PER IL SOFT LIMITER
    THRESH = 20_000
    OUT_THRESH = 24_000

    hp_in = int(memory_buffer[25])
    hp_out = int(memory_buffer[26])

    dc_in = int(memory_buffer[27])
    dc_out = int(memory_buffer[28])


    # ELABORAZIONE
    for i in range(block_size):
        # LETTURA DEL CAMPIONE
        global_index = offset + i
        sample_raw = int(BASE_IN[global_index])

        # SHIFT PER RIMUOVERE LA TRAMA I2S DAL CAMPIONE AUDIO E NORMALIZZARE L'AUDIO PER EVITARE OVERFLOW IN FIXED POINT
        sample_16 = ((sample_raw << 1) >> 16)

        # PASSA ALTO 
        hp = sample_16 - hp_in + ((hp_out * 16319 + 0x2000) >> 14)

        hp_in = sample_16
        hp_out = hp

        sample_16 = hp

        comb_in = (sample_16 + 4) >> 3        # ATTENUAZIONE AGGIUNTIVA DI FREEVERB

        # NOTA: EVENTUALMENTE FARE ((sample_raw << 1) >> 16) >> 1 -> + headroom per i comb
        # e poi successivamente ap_in = comb_sum >> 2

        # REGISTRO PER LE USCITE DAI COMB FILTERS
        comb_sum = 0

        # PARAMETER SMOOTHING
        damp_difference = (damp_target << 10) - damp_current
        if damp_difference > DEADBAND or damp_difference < -DEADBAND:
            damp_current += (damp_difference >> 10)                    # IN QUESTO MODO FACCIO PICCOLI INCREMENTI DI 1/1024 USANDO SOLO INTERI
        else:
            damp_current = (damp_target << 10)                          # CLIPPO IL TARGET PER EVITARE LO STALLO QUANDO INIZIO AD AVVICINARMI AL TARGET

        damp = damp_current >> 10       # VALORE Q15 EFFETTIVO

        feedback_difference = (feedback_target << 10) - feedback_current
        if feedback_difference > DEADBAND or feedback_difference < -DEADBAND:
            feedback_current += (feedback_difference >> 10)
        else:
            feedback_current = (feedback_target << 10)

        feedback = (feedback_current >> 10)

        # OTTO FILTRI COMB (VEDERE QUANTI NE REGGE)

        # --------------------------------------------------- COMB 0: DELAY = 1215, OFFSET = 2048 - 1215 = 833 <-- QUESTO TRUCCHETTO RISPARMIA QUALCHE CICLO DI CPU
        w_index = memory_buffer[0]                                              # PESCO L'INDICE DI SCRITTURA
        r_index = (w_index + 833) & COMB_MASK                                   # CALCOLO L'INDICE DI LETTURA (CON WRAP)

        out_buf = int(memory_buffer[COMB_BASE + r_index])                       # PESCO UN VECCHIO VALORE 

        comb_sum += out_buf                                                     # AGGIORNO LA SOMMA

        prev_state = int(memory_buffer[8])                                      # RECUPERA L'ULTIMO CAMPIONE FILTRATO DALLA MEMORIA PASSA BASSO
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15       # CALCOLA IL CAMPIONE

        memory_buffer[8] = new_state                                            # AGGIORNO LO STATO DEL FILTRO

        # NUOVA AGGIUNTA: CLAMPING INTERMEDIO DELLA MEMORIA
        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)                        # POSSO SOMMARE A prev_state*damp e new_state*feedback 0x4000 per eliminare il bias negativo
                                                                                        # EVITA IL FENOMENO DC Drift DA TRUNCATION ARITMETICO: CONVERTE L'ARROTNDAMENTO DA FLOOR TRUNCATION A NEAREST
        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)
        
        if fb_in > 32767:                                                       
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + w_index] = fb_in
        memory_buffer[0] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 1: DELAY = 1293, OFFSET = 2048 - 1293 = 755
        w_index = memory_buffer[1]
        r_index = (w_index + 755) & COMB_MASK

        out_buf = int(memory_buffer[COMB_BASE + COMB_OFFSET + r_index])

        comb_sum += out_buf

        prev_state = int(memory_buffer[9])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15

        memory_buffer[9] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + COMB_OFFSET + w_index] = fb_in
        memory_buffer[1] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 2: DELAY = 1390, OFFSET = 2048 - 1390 = 658
        w_index = memory_buffer[2]
        r_index = (w_index + 658) & COMB_MASK
        
        out_buf = int(memory_buffer[COMB_BASE + 2*COMB_OFFSET + r_index])
        
        comb_sum += out_buf
        
        prev_state = int(memory_buffer[10])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15
        
        memory_buffer[10] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768
        
        memory_buffer[COMB_BASE + 2*COMB_OFFSET + w_index] = fb_in
        memory_buffer[2] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 3: DELAY = 1476, OFFSET = 2048 - 1476 = 572
        w_index = memory_buffer[3]
        r_index = (w_index + 572) & COMB_MASK
        
        out_buf = int(memory_buffer[COMB_BASE + 3*COMB_OFFSET + r_index])
        
        comb_sum += out_buf
        
        prev_state = int(memory_buffer[11])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15
        
        memory_buffer[11] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + 3*COMB_OFFSET + w_index] = fb_in
        memory_buffer[3] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 4: DELAY = 1548, OFFSET = 2048 - 1548 = 500
        w_index = memory_buffer[4]
        r_index = (w_index + 500) & COMB_MASK
        
        out_buf = int(memory_buffer[COMB_BASE + 4*COMB_OFFSET + r_index])
        
        comb_sum += out_buf
        
        prev_state = int(memory_buffer[12])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15
        
        memory_buffer[12] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + 4*COMB_OFFSET + w_index] = fb_in
        memory_buffer[4] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 5: DELAY = 1623, OFFSET = 2048 - 1623 = 425
        w_index = memory_buffer[5]
        r_index = (w_index + 425) & COMB_MASK
        
        out_buf = int(memory_buffer[COMB_BASE + 5*COMB_OFFSET + r_index])
        
        comb_sum += out_buf
        
        prev_state = int(memory_buffer[13])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15
        
        memory_buffer[13] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + 5*COMB_OFFSET + w_index] = fb_in
        memory_buffer[5] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 6: DELAY = 1695, OFFSET = 2048 - 1695 = 353
        w_index = memory_buffer[6]
        r_index = (w_index + 353) & COMB_MASK
        
        out_buf = int(memory_buffer[COMB_BASE + 6*COMB_OFFSET + r_index])
        
        comb_sum += out_buf
        
        prev_state = int(memory_buffer[14])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15
        
        memory_buffer[14] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + 6*COMB_OFFSET + w_index] = fb_in
        memory_buffer[6] = (w_index + 1) & COMB_MASK

        # --------------------------------------------------- COMB 7: DELAY = 1760, OFFSET = 2048 - 1760 = 288
        w_index = memory_buffer[7]
        r_index = (w_index + 288) & COMB_MASK
        
        out_buf = int(memory_buffer[COMB_BASE + 7*COMB_OFFSET + r_index])
        
        comb_sum += out_buf
        
        prev_state = int(memory_buffer[15])
        new_state = (out_buf * (0x8000 - damp) + prev_state * damp + 0x4000) >> 15
        
        memory_buffer[15] = new_state

        fb_in = comb_in + ((new_state * feedback + 0x4000) >> 15)

        # SOFT-KNEE LIMITER (COMPRESSIONE)
        if fb_in > THRESH:
            fb_in = THRESH + ((fb_in - THRESH + 2) >> 2)    # RATIO 4:1 (OPPURE >> 3 PER 8:1)
        elif fb_in < -THRESH:
            fb_in = -THRESH + ((fb_in + THRESH + 2) >> 2)

        if fb_in > 32767:
            fb_in = 32767
        elif fb_in < -32768:
            fb_in = -32768

        memory_buffer[COMB_BASE + 7*COMB_OFFSET + w_index] = fb_in
        memory_buffer[7] = (w_index + 1) & COMB_MASK


        # ALLPASS 

        # --------------------------------------------------- ALL PASS 0: DELAY = 605 -> OFFSET = 1024 - 605 = 419
        # IL VOLUME POTREBBE ESSERE AUMENTATO DI MOLTO (CON LE 8 SOMME DEL COMB), LO SHIFT A DESTRA DI 3 BIT SERVE A DIVIDERE PER 8 E GARANTIRE UN VOLUME CHE NON ESPLODA
        ap_in = comb_sum

        w_index = memory_buffer[16]
        r_index = (w_index + 419) & ALLPASS_MASK

        out_buf = int(memory_buffer[ALLPASS_BASE + r_index])

        ap_out = -ap_in + out_buf

        memory_buffer[ALLPASS_BASE + w_index] = ap_in + ((out_buf + 1) >> 1)
        memory_buffer[16] = (w_index + 1) & ALLPASS_MASK

        ap_in = ap_out                                                  # PASSA L'USCITA AL FILTRO SUCCESSIVO

        # --------------------------------------------------- ALL PASS 1: DELAY = 480 -> OFFSET = 1024 - 480 = 544

        w_index = memory_buffer[17]
        r_index = (w_index + 544) & ALLPASS_MASK

        out_buf = int(memory_buffer[ALLPASS_BASE + ALLPASS_OFFSET + r_index])

        ap_out = -ap_in + out_buf

        memory_buffer[ALLPASS_BASE + ALLPASS_OFFSET + w_index] = ap_in + ((out_buf + 1) >> 1)
        memory_buffer[17] = (w_index + 1) & ALLPASS_MASK

        ap_in = ap_out   

        # --------------------------------------------------- ALL PASS 2: DELAY = 371 -> OFFSET = 1024 - 371 = 653
        
        w_index = memory_buffer[18]
        r_index = (w_index + 653) & ALLPASS_MASK
        
        out_buf = int(memory_buffer[ALLPASS_BASE + 2*ALLPASS_OFFSET + r_index])
        
        ap_out = -ap_in + out_buf
        
        memory_buffer[ALLPASS_BASE + 2*ALLPASS_OFFSET + w_index] = ap_in + ((out_buf + 1) >> 1)
        memory_buffer[18] = (w_index + 1) & ALLPASS_MASK
        
        ap_in = ap_out   

        # --------------------------------------------------- ALL PASS 3: DELAY = 245 -> OFFSET = 1024 - 245 = 779
        
        w_index = memory_buffer[19]
        r_index = (w_index + 779) & ALLPASS_MASK
        
        out_buf = int(memory_buffer[ALLPASS_BASE + 3*ALLPASS_OFFSET + r_index])
        
        ap_out = -ap_in + out_buf
        
        memory_buffer[ALLPASS_BASE + 3*ALLPASS_OFFSET + w_index] = ap_in + ((out_buf + 1) >> 1)
        memory_buffer[19] = (w_index + 1) & ALLPASS_MASK
        
        # MIXING
        y = ap_out

        # SOFT-KNEE PIÙ DECISO (SOMMO 8 COMB IN PARALLELO)
        if y > OUT_THRESH:
            y = OUT_THRESH + ((y - OUT_THRESH + 4) >> 3)        # COMPRESSIONE 8:1
        elif y < -OUT_THRESH:
            y = -OUT_THRESH + + ((y + OUT_THRESH + 4) >> 3)

        # BLOCCO DC
        out = y - dc_in + ((dc_out * 16350 + 0x2000) >> 14)
        dc_in = y
        dc_out = out

        y = out

        # CLIPPING A 16 BIT CA 2 (SCRITTO IN DECIMALE PER SICUREZZA, VIPER POTREBBE CREARE PROBLEMI CON I SIGNED ESADECIMALI)
        if y > 32767:
            y = 32767
        elif y < -32768:
            y = -32768


        # SCRITTURA DELL'USCITA
        BASE_OUT[global_index] = (y << 15)

    # SALVATAGGIO DELLO STATO PER I BLOCCHI SUCCESSIVI
    memory_buffer[23] = damp_current
    memory_buffer[24] = feedback_current

    memory_buffer[25] = hp_in
    memory_buffer[26] = hp_out

    memory_buffer[27] = dc_in
    memory_buffer[28] = dc_out