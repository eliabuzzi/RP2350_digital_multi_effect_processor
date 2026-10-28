import rp2, array

BUFFER_LENGTH_REV = const(0x5020)
BUFFER_LENGTH_ECHO = const(0x8020 // 2)
BUFFER_LENGTH_BITCRUSH = const(8)


zero = array.array('I', [0])
dma_flush = rp2.DMA()

flush_ctrl = dma_flush.pack_ctrl(
    size = 2,
    inc_read = False,
    inc_write = True
)

def dma_clear(buffer, n_words):
    dma_flush.config(
        read = zero,
        write = buffer,
        count = n_words,
        ctrl = flush_ctrl,
        trigger = True
    )

    # CHIAMA IL DMA CHE SCRIVE N PAROLE A 0 SUL BUFFER E POI SI DISATTIVA
    while dma_flush.active():
        pass