# CODICE IL FLUSH DELLE MEMORIE
import micropython
from micropython import const
#from machine import mem32

BLOCK_SIZE = const(64)
BUFFER_LENGTH_REV = const(0x5020)
BUFFER_LENGTH_ECHO = const(0x8004 // 2)
BUFFER_LENGTH_BITCRUSH = const(4)

@micropython.viper

def dsp_viper_memory_flush(reverb_buffer: ptr32, delay_buffer: ptr32, bitcrush_buffer: ptr32):

    # DEVO SOVRASCRIVERE A 0 LE MEMORIE DEI DATI E DEGLI INDICI
    for i in range(BUFFER_LENGTH_REV):
        reverb_buffer[i] = 0

    for j in range(BUFFER_LENGTH_ECHO):
        delay_buffer[j] = 0

    for k in range(BUFFER_LENGTH_BITCRUSH):
        bitcrush_buffer[k] = 0