# CODICE PER IL FADE IN / FADE OUT

import micropython
from micropython import const

BLOCK_SIZE = const(64)
N = const(16)                       # SPALMA LA RAMPA SU 16 CAMPIONI A INCREMENTO

@micropython.viper

def dsp_viper_mute(block_index: int, target_volume: int, state_buffer: ptr32, mode: int):
    # BASI PER I BUFFER IN INGRESSO E USCITA (CON CONTROLLO DELLA MODALITÀ)
    BASE_OUT = ptr32(0x20074000)

    if mode == 0:                       # LEGGE DAL BUFFER IN INGRESSO

        BASE_IN = ptr32(0x2006C000)

    else:

        BASE_IN = BASE_OUT              # SOVRASCRIVE IL BUFFER IN USCITA


    

    #state_buffer = ptr32(state_buffer_addr)

    # TARGET: 0 (MUTO), 256 (SMUTATO) - ORA PER DEBUG 1024

    last_value_vol = int(state_buffer[0])   # VOLUME ATTUALE MANTENUTO IN MEMORIA TRA UNA CHIAMATA E L'ALTRA

    offset = block_index * BLOCK_SIZE   # OFFSET ALL'INTERNO DEL BUFFER IN RAM

    for i in range(BLOCK_SIZE):
        # INDICE GLOBALE
        global_index = offset + i

        # LEGGE IL CAMPIONE E LO ALLINEA
        sample_raw = int(BASE_IN[global_index])

        sample_24 = (sample_raw << 1) >> 8

        # INCREMENTA LA RAMPA OGNI N CAMPIONI
        if (i & ((1 << N) - 1)) == 0:
            # RAMPA LINEARE VERSO IL TARGET
            if last_value_vol < target_volume:
                last_value_vol += 1             # FADE IN
            elif last_value_vol > target_volume:
                last_value_vol -= 1             # FADE OUT

        # APPLICA LA VARIAZIONE DI VOLUME
        sample = (sample_24 * last_value_vol) >> 8

        # SCRIVE IL DATO SUL BUFFER D'USCITA RIPORTANDOLO NEL FORMATO I2S
        BASE_OUT[global_index] = (sample << 7)

    # SALVO IL VALORE PER LA CHIAMATA SUCCESSIVA
    state_buffer[0] = last_value_vol