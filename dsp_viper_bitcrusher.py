import micropython

# EFFETTO "ZERO RAM", USIAMO UN SEMPLICE BUFFER PER MANTENERE IN MEMORIA LA VERSIONE LOCALE E IL VALORE DELL'EFFETTO PER IL PARAMETER SMOOTHING
# STRUTTURA:
# [0] = LOCAL VERSION
# [1] = LAST VALUE POT
# [2] = LAST VALUE SHIFT (DA 0 A 13)    LIMITIAMO LOS HIFT PER NON CREARE ONDE QUADRE PERFETTE
# [3] = MEMORIA PASSA BASSO PRIMO POLO
# [4] = MEMORIA PASSA BASSO SECONDO POLO

@micropython.viper

def dsp_viper_bitcrusher(block_index: int, global_version: int, parameters_addr: int, memory_buffer: ptr32):

    # BASI PER LA LETTURA / SCRITTURA DEI CAMPIONI
    BASE_IN = ptr32(0x2006C000)
    BASE_OUT = ptr32(0x20074000)

    # RISOLVO L'INDIRIZZO PER LEGGERE I POTENZIOMETRI
    parameters = ptr32(parameters_addr)

    # CONFRONTO TRA LE VERSIONI
    local_version = int(memory_buffer[0])
    adc_current = int(memory_buffer[1])
    shift_current = int(memory_buffer[2])

    if local_version != global_version:

        adc_target = int(parameters[0])

        # CONTROLLO PER AGGIORNARE IL VALORE SOLO SE HA SUPERATO UNA SOGLIA DI TOLLERANZA (EVITA IL FLICKERING VICINO AI BORDI)
        adc_diff = adc_target - adc_current

        # MAPPATURA A SCAGLIONI, IL MASSIMO CHE RICEVIAMO DALL'ADC È (IN Q15) 32768
        # QUINDI 32767 >> 11 = 15 (NON DEVO SHIFTARE)
        #        0 >> 11 = 0        (SHIFTO DI 15 POSIZIONI)

        if adc_diff > 100 or adc_diff < -100 or local_version == 0: # INIZIALIZZA CORRETTAMENTE DOPO IL FLUSH
            adc_current = adc_target

            n = (adc_current * 13) >> 15
            if n > 12:  
                n = 12      # CLAMPING DEL VALORE MASSIMO

            shift_current = 12 - n

            # SALVO I VALORI IN MEMORIA
            memory_buffer[1] = adc_current
            memory_buffer[2] = shift_current

        # AGGIORNO LA VERSIONE GLOBALE 
        memory_buffer[0] = global_version

    block_size = 64
    offset = block_index * block_size

    # COSTANTI
    GAIN_STEP = 650             # CIRCA -2.4 db A SHIFT, REGOLARE A ORECCHIO
    LP_ATT = 18_000             # POLO A 6khz

    # FILTRO PASSA BASSO A DUE POLI
    lp1_in = int(memory_buffer[3])
    lp2_in = int(memory_buffer[4])

    shift = shift_current
    dc_offset = (1 << shift) >> 1       # OFFSET PER L'ARROTONDAMENTO
    gain = 32768 - shift * GAIN_STEP

    # ELABORAZIONE AUDIO
    for i in range(block_size):

        # LETTURA DEL CAMPIONE
        global_index = offset + i
        sample_raw = int(BASE_IN[global_index])

        # RIMUOVO LA TRAMA I2S DAL CAMPIONE AUDIO
        sample_16 = (sample_raw << 1) >> 16

        # BITCRUSH: SHIFTO A DESTRA E POI RISHIFTO A SINISTRA PER NORMALIZZARE L'AMPIEZZA
        y = ((sample_16 + dc_offset) >> shift) << shift

        if y > 32767:
            y = 32767
        elif y < -32768:
            y = -32768

        # FILTRO PASSA BASSO A DUE POLI
        lp1_in += ((y - lp1_in) * LP_ATT + 0x4000) >> 15
        lp2_in += ((lp1_in - lp2_in) * LP_ATT + 0x4000) >> 15
        y = lp2_in

        # GAIN STAGING
        y = (y * gain + 0x4000) >> 15

        if y > 32767:
            y = 32767
        elif y < -32768:
            y = -32768

        # SCRITTURA DELL'USCITA
        BASE_OUT[global_index] = (y << 15)

    memory_buffer[3] = lp1_in
    memory_buffer[4] = lp2_in