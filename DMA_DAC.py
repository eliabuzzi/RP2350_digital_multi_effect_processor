import rp2

# CONFIGURAZIONE DMA TRASMISSIONE
PIO_TX_DREQ = 8                             # 8: DREQ_PIO1_TX0 (DATASHEET RP2040: 2.5.3.1. System DREQ Table)
TX_A = 0x20074000
DMA_WORDS = 64  

def dma_dac(sm):

    dma_tx = rp2.DMA()

    dma_tx_ctrl = dma_tx.pack_ctrl(
        size = 2,                               # PAROLE DA 32 BIT
        inc_read=True,                          # INCREMENTA L'INDIRIZZO DI LETTURA
        inc_write=False,                        # NON INCREMENTARE L'INDIRIZZO DI SCRITTURA (LA PIO)
        treq_sel=PIO_TX_DREQ,                   # TRANSFER REQUEST
        ring_size=14,                           # NUMERO DI BIT SU CUI GESTISCE IL WRAP
        ring_sel=False,                         # False = ATTIVA IL RING SULLA LETTURA
        irq_quiet=True                          # IL DMA DEV'ESSERE SILENZIOSO, NON DEVE GENERARE INTERRUPT
    )

    dma_tx.config(
        read=TX_A,
        write=sm,

        count=(DMA_WORDS | 0x10000000),         # MODALITÀ TRIGGER SELF (DATASHEET RP2350: 12.6.2.2.1. Count modes)
        ctrl=dma_tx_ctrl,
        trigger=False
    )

    return dma_tx