from machine import I2C, Pin
import ssd1306
import time

# Comandi registro hardware SSD1306 per l'aggiornamento parziale
SET_COL_ADDR  = 0x21
SET_PAGE_ADDR = 0x22

class LCDscreen:
    def __init__(self, sda_gpio=12, scl_gpio=13, n_rows=2, n_col=16):
        # I2C tirato a 1 MHz per la massima velocità di trasferimento
        self.i2c = I2C(0, sda=Pin(sda_gpio), scl=Pin(scl_gpio), freq=1_000_000)
        addr_list = self.i2c.scan()
        
        if not addr_list:
            print("ERRORE! Nessun display OLED trovato")
            return
            
        self.lcd = ssd1306.SSD1306_I2C(128, 64, self.i2c, addr=addr_list[0])
        
        # Coordinate Y suddivise in "pagine" di memoria (0-7) da 8 pixel l'una
        self.page_p1 = 3  # Riga parametro 1 (Y = 24)
        self.page_p2 = 6  # Riga parametro 2 (Y = 48)
        self.col_val = 7  # Indice carattere da cui parte il valore numerico
        
        self.clear()

    # -------------------------------------------------------------------------
    # ROUTINE ULTRA-RAPIDA (< 0.4 ms) PER I POTENZIOMETRI
    # -------------------------------------------------------------------------
    def _write_val_fast(self, pot_value, page, col_start_char):
        """Invia via I2C solo i 32 pixel interessati dalla modifica del valore"""
        # 1. Forza la stringa a 4 caratteri esatti
        text = f"{str(pot_value):<4}"[:4]
        
        # 2. Calcola le coordinate hardware
        x0 = col_start_char * 8
        x1 = x0 + 31
        
        # 3. Aggiorna solo quel microscopico blocco nel buffer Python
        self.lcd.fill_rect(x0, page * 8, 32, 8, 0)
        self.lcd.text(text, x0, page * 8, 1)
        
        # 4. Estrapola i 32 byte esatti dalla RAM
        buffer_offset = (page * 128) + x0
        data_slice = memoryview(self.lcd.buffer)[buffer_offset : buffer_offset + 32]
        
        # 5. Spedisce il payload minimo indispensabile all'OLED
        addr = self.lcd.addr
        self.i2c.writeto(addr, b'\x00' + bytes([SET_COL_ADDR, x0, x1, SET_PAGE_ADDR, page, page]))
        self.i2c.writeto(addr, b'\x40' + data_slice)

    # -------------------------------------------------------------------------
    # METODI ORIGINALI DEL TUO MAIN (COMPATIBILITÀ 100%)
    # -------------------------------------------------------------------------
    def clear(self):
        self.lcd.fill(0)
        self.lcd.show()

    def off(self):
        self.lcd.poweroff()

    def on(self):
        self.lcd.poweron()

    def boot(self, text_1, text_2=""):
        self.lcd.fill(0)
        self.lcd.text(text_1, 0, 4)
        self.lcd.hline(0, 18, 128, 1)
        if text_2:
            self.lcd.text(text_2, 0, 28)
        self.lcd.show()

    def show_menu(self, effect, next_effect):
        self.lcd.fill(0)
        self.lcd.text("SELECT EFFECT:", 0, 2)
        self.lcd.hline(0, 14, 128, 1)
        self.lcd.text(f"-> {effect}", 0, 26)
        self.lcd.text(f"   {next_effect}", 0, 46)
        self.lcd.show()

    def write_effect(self, effect):             
        self.lcd.fill_rect(0, 0, 128, 16, 0)
        self.lcd.text(f"[{effect}]", 0, 2)
        self.lcd.hline(0, 14, 128, 1)
        self.lcd.show()
    
    def write_labels(self, p1_label="--", p2_label="--", p1_value="0.00", p2_value="0.00"):
        self.lcd.fill_rect(0, 16, 128, 48, 0)
        self.lcd.text(f"{p1_label[:6]:<6}:", 0, self.page_p1 * 8)
        self.lcd.text(f"{p2_label[:6]:<6}:", 0, self.page_p2 * 8)
        self.lcd.show()
        # Allinea il buffer locale usando la funzione rapida
        self._write_val_fast(p1_value, self.page_p1, self.col_val)
        self._write_val_fast(p2_value, self.page_p2, self.col_val)

    def write_p1_value(self, pot_value):        
        self._write_val_fast(pot_value, self.page_p1, self.col_val)
    
    def write_p2_value(self, pot_value):
        self._write_val_fast(pot_value, self.page_p2, self.col_val)
    
    def update_old(self, effect_name, par_1, par_2, par_1_value, par_2_value):
        self.lcd.fill(0)
        self.lcd.text(f"[{effect_name}]", 0, 2)
        self.lcd.hline(0, 14, 128, 1)
        self.lcd.text(f"{par_1[:6]:<6}: {par_1_value:<4}", 0, self.page_p1 * 8)
        self.lcd.text(f"{par_2[:6]:<6}: {par_2_value:<4}", 0, self.page_p2 * 8)
        self.lcd.show()


# ==============================================================================
# MAIN DIMOSTRATIVO PER IL TEST
# ==============================================================================
#if __name__ == "__main__":
#    
#    print("Avvio test display a 3 righe con Partial Update I2C...")
#    lcd = LCDscreen(sda_gpio=12, scl_gpio=13)
#
#    print("1. Schermata di Boot (Operazione lenta, tollerata all'avvio)")
#    lcd.boot("RP2350 DSP", "Engine Started")
#    time.sleep(2)
#
#    print("2. Scorrimento Menu (Operazione lenta, non suoni mentre lo usi)")
#    lcd.show_menu("TAPE DELAY", "FREEVERB")
#    time.sleep(1.5)
#
#    print("3. Setup layout effetto (Lento, eseguito 1 sola volta al cambio)")
#    lcd.write_effect("TAPE DELAY")
#    lcd.write_labels(p1_label="TIME", p2_label="FDBK", p1_value="120", p2_value="40")
#    time.sleep(2)
#
#    print("4. SIMULAZIONE I2S: Tweak parametri IN TEMPO REALE (Operazione ultra-rapida 0.38ms)")
#    # Noterai che l'aggiornamento di questi valori è talmente istantaneo da non
#    # generare sfarfallio sull'OLED. Eseguirle non sfonderà il budget di 1.33ms.
#    for i in range(120, 250, 10):
#        lcd.write_p1_value(str(i))
#        time.sleep(0.05) 
#
#    for i in range(40, 85, 5):
#        lcd.write_p2_value(str(i))
#        time.sleep(0.05)
#
#    print("Test completato.")
#    time.sleep(1)
#    lcd.clear()