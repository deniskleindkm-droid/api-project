# Silverbene Wave-1 probe (read-only)

Probed 2026-09-24T01:31:18.920224+00:00; option_ids 57451, 57442, 57439.
Rate-call latency (successful calls): {'n': 31, 'min': 6.21, 'median': 51.42, 'max': 110.02}

Country-list endpoints tried: get_country=404, country_list=404, countries=404, get_countries=HTTPSConnectionPool(host='s.silverbene.com', port=443): Max retries exceeded with url: /api/dropshipping/get_countries?token=<redacted> (Caused by ConnectTimeoutError(<HTTPSConnection(host='s.silverbene.com', port=443) at 0x14f97a47250>, 'Connection to s.silverbene.com timed out. (connect timeout=20)'))


## US (country_id `US`) supported=True standard=True express=True
- **Chicago 60601** [ok, 30.87s, USD]
  - EXPRESS  `DHLI` DHL Express(4 - 9 workdays, customs duty included) — $57.83
  - EXPRESS  `FedexI` FedEx(4 - 9 workdays, customs duty included) — $62.41
  - STANDARD `ITDIDA_ECO` International Standard(12-20 workdays) — $5.52 ⚠ duplicate method id
- **Atlanta 30303** [ok, 53.36s, USD]
  - EXPRESS  `DHLI` DHL Express(4 - 9 workdays, customs duty included) — $57.83
  - EXPRESS  `FedexI` FedEx(4 - 9 workdays, customs duty included) — $62.41
  - STANDARD `ITDIDA_ECO` International Standard(12-20 workdays) — $5.52 ⚠ duplicate method id
- **Los Angeles 90012** [ok, 75.32s, USD]
  - EXPRESS  `DHLI` DHL Express(4 - 9 workdays, customs duty included) — $57.83
  - EXPRESS  `FedexI` FedEx(4 - 9 workdays, customs duty included) — $62.61
  - STANDARD `ITDIDA_ECO` International Standard(12-20 workdays) — $5.52 ⚠ duplicate method id
- 3 items at Chicago 60601 via `DHLI` (EXPRESS): one shipment $66.22 vs three orders $169.87
- 3 items at Chicago 60601 via `FedexI` (EXPRESS): one shipment $70.79 vs three orders $183.61
- 3 items at Chicago 60601 via `ITDIDA_ECO` (STANDARD): one shipment $5.52 vs three orders $16.56
- ambiguous method ids: ['ITDIDA_ECO']

## GB (country_id `GB`) supported=True standard=True express=True
- **London SW1A 1AA** [ok, 26.55s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $45.89
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $27.56
  - STANDARD `cainiao` Cainiao International — $10.64
  - STANDARD `ITDIDA_ECO` International Economy(9 workdays) — $4.21
- **Manchester M1 1AE** [ok, 76.22s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $45.89
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $27.56
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $13.22
  - STANDARD `cainiao` Cainiao International — $10.64
  - STANDARD `ITDIDA_ECO` International Economy(9 workdays) — $4.21
- 3 items at London SW1A 1AA via `Fedex` (EXPRESS): one shipment $27.56 vs three orders $82.68
- 3 items at London SW1A 1AA via `BKPHR` (STANDARD): one shipment $24.47 vs three orders $None
- 3 items at London SW1A 1AA via `cainiao` (STANDARD): one shipment $10.64 vs three orders $31.92
- 3 items at London SW1A 1AA via `ITDIDA_ECO` (STANDARD): one shipment $4.21 vs three orders $12.63

## DE (country_id `DE`) supported=True standard=True express=True
- **Berlin 10115** [ok, 110.02s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $49.37
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $32.13
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $17.76
  - STANDARD `cainiao` Cainiao International — $15.57
- **Munich 80331** [ok, 93.17s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $49.37
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $32.13
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $17.76
  - STANDARD `cainiao` Cainiao International — $15.57
  - STANDARD `ITDIDA_ECO` International Economy(9 workdays) — $12.18
- 3 items at Berlin 10115 via `DHL` (EXPRESS): one shipment $49.37 vs three orders $148.11
- 3 items at Berlin 10115 via `Fedex` (EXPRESS): one shipment $32.13 vs three orders $96.39
- 3 items at Berlin 10115 via `BKPHR` (STANDARD): one shipment $29.03 vs three orders $None
- 3 items at Berlin 10115 via `cainiao` (STANDARD): one shipment $15.57 vs three orders $46.71
- 3 items at Berlin 10115 via `ITDIDA_ECO` (STANDARD): one shipment $12.18 vs three orders $None

## FR (country_id `FR`) supported=True standard=True express=True
- **Paris 75001** [ok, 86.85s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $49.37
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $32.13
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $17.9
  - STANDARD `cainiao` Cainiao International — $16.48
  - STANDARD `ITDIDA_ECO` International Economy(9 workdays) — $11.93
- **Lyon 69001** [ok, 80.02s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $49.37
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $32.13
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $17.9
  - STANDARD `cainiao` Cainiao International — $16.48
  - STANDARD `ITDIDA_ECO` International Economy(9 workdays) — $11.93
- 3 items at Paris 75001 via `DHL` (EXPRESS): one shipment $49.37 vs three orders $148.11
- 3 items at Paris 75001 via `Fedex` (EXPRESS): one shipment $32.13 vs three orders $96.39
- 3 items at Paris 75001 via `BKPHR` (STANDARD): one shipment $29.16 vs three orders $48.84
- 3 items at Paris 75001 via `cainiao` (STANDARD): one shipment $16.48 vs three orders $49.44
- 3 items at Paris 75001 via `ITDIDA_ECO` (STANDARD): one shipment $11.93 vs three orders $35.79

## AU (country_id `AU`) supported=True standard=True express=True
- **Melbourne 3000** [ok, 6.21s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $36.02
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $36.36
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $16.34
  - STANDARD `cainiao` Cainiao International — $9.96
- **Sydney 2000** [ok, 51.15s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $36.02
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $36.36
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $16.34
  - STANDARD `cainiao` Cainiao International — $9.96
- 3 items at Sydney 2000 via `DHL` (EXPRESS): one shipment $36.02 vs three orders $108.06
- 3 items at Sydney 2000 via `Fedex` (EXPRESS): one shipment $36.36 vs three orders $109.08
- 3 items at Sydney 2000 via `BKPHR` (STANDARD): one shipment $27.57 vs three orders $None
- 3 items at Sydney 2000 via `cainiao` (STANDARD): one shipment $9.96 vs three orders $29.88

## CA (country_id `CA`) supported=True standard=True express=True
- **Vancouver V6B 1A1** [ok, 17.52s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $36.93
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $33.71
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $15.02
  - STANDARD `cainiao` Cainiao International — $14.13
- **Toronto M5H 2N2** [ok, 26.0s, USD]
  - EXPRESS  `DHL` DHL Express(4 - 9 workdays) — $36.93
  - EXPRESS  `Fedex` FedEx(4 - 9 workdays) — $33.71
  - STANDARD `BKPHR` YunExpress Registered Priority General(2-10 workdays,TAX included) — $15.02
  - STANDARD `cainiao` Cainiao International — $14.13
- 3 items at Toronto M5H 2N2 via `DHL` (EXPRESS): one shipment $36.93 vs three orders $110.79
- 3 items at Toronto M5H 2N2 via `BKPHR` (STANDARD): one shipment $26.2 vs three orders $40.24
- 3 items at Toronto M5H 2N2 via `cainiao` (STANDARD): one shipment $14.13 vs three orders $None
