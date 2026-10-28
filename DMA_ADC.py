import rp2
#import dsp_test
import machine
from core_events import send_event

#rx_buffer = array.array("I", [0] * DMA_WORDS)  # CREA UN ARRAY DI 4096 PAROLE DA 32 BIT

# CONFIGURAZIONE DMA RICEZIONE
PIO_RX_DREQ = 4             # DREQ PER PIO0 - RX0
DMA_WORDS = 64 
RX_A = 0x2006C000
#irq_count = 0               # PER DEBUG, VERIFICARE DI OTTENERE 16 IRQ PER CICLO DI RIEMPIMENTO BUFFER

# CONFIGURAZIONE PARAMETRI
#BLOCK_SIZE = 64#256                # SUCCESSIVAMENTE = DMA_WORDS
N_BLOCKS = 64#16                  
WRAP_MASK = N_BLOCKS - 1        # IN QUESTO CASO 15: 1111 o 0x000F

MAILBOX_BASE = 0x2007C000       # EQ A CTRL_REG

# BASE DELLA MAILBOX
# ADDR_DMA_INDEX = MAILBOX_BASE + 0x00       # SCRITTO DALL'IRQ HANDLER DEL DMA

# NOTA: FIFO TX: DALLA CPU A PIO, FIFO RX: DALLA PIO ALLA CPU 

def dma_adc(sm):
    dma_rx = rp2.DMA()

    dma_rx_ctrl = dma_rx.pack_ctrl(
        size=2,                         # 2 = PAROLE DA 32 BIT
        inc_read=False,                 # NON INCREMEMNTARE L'INDIRIZZO DI LETTURA (LEGGO SEMPRE DALLA STESSA FIFO)
        inc_write=True,                 # INCREMENTA L'INDIRIZZO DI SCRITTURA (AVANZA NEL BUFFER RAM)
        treq_sel=PIO_RX_DREQ,            # SELEZIONE DEL TRANSFER REQUEST
        ring_size=14,                   # (IN BYTE) 2^12 * 2^2 = 2^14, GESTISCE IL WRAP AUTOMATICO DELL'INDIRIZZO DI SCRITTURA
        ring_sel=True,                   # ATTIVA IL RING ALL'INDIRIZZO DI SCRITTURA (False = attiva all'indirizzo in lettura)
        irq_quiet=False                  # PERMETTE AL CONTROLLER DEL DMA DI INVIARE UN SEGNALE DI INTERRUPT
    )

    # ABILITO IL SELF TRIGGER PER IL DMA: REGISTRO TRANS_COUNT, mode (TRIGGER_SELF) = 0x1
    dma_rx.config(
        read=sm,                       # LEGGE DALLA FIFO DELLA SM
        write=RX_A,                # SALVA LE PAROLE NEL BUFFER
        count=(DMA_WORDS | 0x10000000),   # NUMERO DI TRASFERIMENTI ESEGUITI PRIMA DI BLOCCARE IL CANALE | MODALITA' TRIGGER_SELF
        ctrl=dma_rx_ctrl,               # CONTROLLER DEL DMA
        trigger=False                       # NON AVVIARTI AUTOMATICAMENTE MA ASPETTA LA CHIAMATA ALLA FUNZIONE .active(1)
    )

    # PROCEDURA EFFETTUATA DOPO L'IRQ -- TEST INIZIALE
    #def dma_rx_irq_handler(dma):
    #    global irq_count
    #    irq_count += 1

    # IRQ PER IL DSP:
    # DEVE GESTIRE SOLO ED ESCLUSIVAMENTE L'AVANZAMENTO DELL'INDICE UNIVERSALE PER IL BLOCCO DA ELABORARE
    def dma_rx_irq_handler(_):
        #global record_index, last_irq_start

        # INGRESSO NELL'INTERRUPT
        #t0 = time.ticks_us()

        # TEMPO TRASCORSO DALL'ULTIMO INTERRUPT (QUANTO STA IL DMA A RIEMPIRE IL BLOCCO)
        #if record_index < MAX_RECORDS:
        #    dma_rx_transfer_time[record_index] = time.ticks_diff(t0, last_irq_start)

        #last_irq_start = t0         # ORA LO USO PER MISURARE IL TEMPO DI GESTIONE DELL'INTERRUPT
    
        # READ - MODIFY- WRITE PER PASSARE IL NUMERO DEL BLOCCO DA ELABORARE
        current_dma_index = machine.mem32[MAILBOX_BASE]
        machine.mem32[MAILBOX_BASE] = (current_dma_index + 1) & WRAP_MASK


        # NOTIFICA IL CORE 1 (DSP) E LO RISVEGLIA
        send_event()

        # FINE DELL'INTERRUPT, VERIFICO IL TEMPO
        #t1 = time.ticks_us()

        # SALVO I DATI NELL'ARRAY
        #if record_index < MAX_RECORDS:
        #    irq_handler_time[record_index] = time.ticks_diff(t1, t0)
        #    record_index += 1


    # ABILITO L'HANDLER PER L'IRQ
    dma_rx.irq(
        handler=dma_rx_irq_handler,
        hard=True                       # SE POSSIBILE, ESEGUE IL GESTORE DIRETTAMENTE NEL CONTESTO DELL'INTERRUPT (SENZA PASSARE PER MICROPYTHON)
        
        
        #hard = False                     # PER ORA SOFT IRQ: PERMETTE L'USO DEI LOCK DIRETTAMENTE NELL'IRQ HANDLER
    )

    return dma_rx
