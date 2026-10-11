# Test Grove OLED e buzzer — UNO Q

Base Shield V2 su **3.3V**, buzzer passivo nella presa **D4**, OLED nella presa **I2C**.
Il driver è per Grove OLED 128×64 SSD1315/SSD1306; il modello SSD1308 va verificato separatamente.

L'OLED mostra un numero pseudocasuale 0–9999 ogni secondo e il tempo dall'avvio.
Il buzzer emette un solo beep di circa 300 ms, cinque secondi dopo l'inizio di setup().
Ogni riavvio dello sketch ripete il beep. La generazione software del suono può
produrre una durata/frequenza leggermente diversa in funzione del carico del MCU.

LED singoli con una resistenza da 330 ohm ciascuno e catodi a GND:
presa D2, filo giallo -> verde (D2), filo bianco -> giallo (D3);
presa D6, filo giallo -> rosso (D6), filo bianco -> alert bianco (D7).
Semaforo in ciclo verde -> giallo -> rosso, due secondi per colore.
Alert bianco sempre lampeggiante, 500 ms acceso / 500 ms spento, anche durante il beep.

## Avvio su scheda

Copia questa cartella in `~/ArduinoApps/grove_oled_buzzer_test` sulla UNO Q, poi:

```bash
arduino-app-cli app start ~/ArduinoApps/grove_oled_buzzer_test
```

Oppure importa la cartella in Arduino App Lab e premi Run.
Il profilo installa U8g2 2.36.5. Questo test sostituisce il firmware MCU crosswalk.

## Streaming cam0

Questa app non avvia né arresta la camera. Mantieni il processo Linux di streaming
già attivo, separato dall'app MCU. Se lo streaming era un subprocess gestito dalla
vecchia app App Lab, separalo da quell'app prima di arrestarla.
Nel progetto la pipeline CAM0 si avvia sulla scheda con:

```bash
cd ~/occhio
libcamerify .venv/bin/python -m crosswalk --config configs/board_imx219.yaml
```

Il video è su `http://<IP-scheda>:8000/video.mjpg`. Il test non fornisce gli RPC del
firmware crosswalk: lo stato MCU della dashboard può risultare scollegato mentre
camera e pipeline Linux continuano a funzionare.

## Verifica su scheda — 10 ottobre 2026

Caricata via SSH nell'account `arduino` della UNO Q alle 17:16 circa (Europe/Rome).
Compilazione, flash e avvio App Lab riusciti; app nello stato `running` e Python
senza errori nei log di avvio. La pipeline CAM0 esistente è rimasta attiva:
stream MJPEG HTTP 200 con 234451 byte ricevuti in quattro secondi, contatore
camera a 35603 frame e acquisizione a circa 36,5 fps dopo il caricamento.
La conferma visiva dell'OLED e sonora del beep resta all'operatore.

Aggiornamento LED caricato e app riavviata con successo alle 17:42 circa.
In questa sessione la pipeline CAM0 risultava già ferma: riavviata separatamente
con la configurazione `board_imx219.yaml`. App LED nello stato `running`.
