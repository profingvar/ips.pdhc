# EPS och patient-state i ips.pdhc — plan

**Utgångspunkt.** `docs/EPS_patientoversikt.docx` och
`docs/EPS_sektioner_vokabularer.xlsx`, båda daterade 2026-10-30. Mätningarna som
planen bygger på står i `plans/eps_state_reform.md` och upprepas inte här;
varje steg nedan hänvisar till det avsnitt som motiverar det.

**Förhållande till epic #788.** `plans/euips_reform.md` är planen för euIPS och
bygger på ett **äldre och annat** källdokument,
`docs/EU_Patient_Summary_ICD11.docx`. Den planen ersätts inte. Den här planen
tar vid där den slutar: vad den nyare EPS-specifikationen lägger till, och vad
tillståndsmodellen behöver som ingen av planerna har.

**Numreringen följer husets konvention (Rule 3)**, och varje steg har ett
*klart när* som är mätbart. Ett steg vars klart-när är en konvention är inte
klart — det är dokumenterat.

---

## 0. Beslut som måste tas före bygget

Samma klass som D1–D3 i `alert.pdhc`: varje beslut går in i varje rad som
skrivs efteråt, och att ändra det senare är en ommigrering, inte en rättning.
Inget steg i fas 2 eller 3 bör startas innan motsvarande beslut är taget.

| | beslut | rekommendation | blockerar |
|---|---|---|---|
| **E1** | R4 eller R5 på EPS:s exportväg? | **Behåll R5 internt, rendera R4 bara vid export** | 2.e |
| **E2** | Var bor tillståndsdata? | **Egen append-only-tabell**, inte `fhir_resources` | hela fas 3 |
| **E3** | Vad är ett anhörigprivilegium? | **Ett tidsbegränsat, granskningsbart medgivande vid sidan av `patient_consents`** | 3.d, 3.e |

### E1 — versionen

EPS är **FHIR R4**. Tjänsten deklarerar `fhirVersion: 5.0.0` och euIPS-byggarna
emitterar R5-former medvetet, med skillnaderna redan flaggade i koden
(`Coverage.kind`/`insurer` mot R4:s `payor`; `attester.mode` som
CodeableConcept). Ett konformt EPS-paket kan alltså inte vara R5.

Att flytta hela tjänsten till R4 är bakvänt — R5 är den nyare standarden och tio
syskontjänster är byggda mot den här R5-ytan. Att hävda konformitet från
R5-utdata är inte tillgängligt, därför att det vore falskt. Kvar står att
rendera R4 på den enda väg där konformitet hävdas. Se bedömningen §2.6.

### E2 — var state bor

#791 beslutade att **kliniskt** innehåll bor i `fhir_resources` och att inga nya
tabeller läggs till. Det beslutet står. Tillståndsdata är inte kliniskt
innehåll, och tre skäl talar för en egen tabell:

1. Giltighetstid är inte ett enhetligt FHIR-resursfält. `Address` har `period`,
   men en kontaktuppgift, en klinikkoppling och ett anhörigprivilegium har var
   sin plats — eller ingen.
2. `patient_index` är redan en **projektion**: `_sync_patient_index()` bygger om
   den ur Patient-resursen vid varje skrivning. Att lägga state där vore en
   andra sanningskälla för fakta som bor någon annanstans, vilket är formen på
   #779 och #771.
3. Tabellen kan göras append-only från början, vilket `fhir_resources` är i
   praktiken men inte i schemat.

**Skillnaden mot #791 måste skrivas ut i koden**, annars läser nästa person ett
av de två besluten som ett misstag.

### E3 — anhörigprivilegiet

`care_access_policy.py` kallar sig själv den enda källan till zonregeln, och
varje argument den tar är en vårdidentitet. Det finns ingen zon, ingen grund och
inget argument för en privatperson som agerar på patientens uppdrag.

Det billigare alternativet — en flagga på en kontaktuppgift — kan inte granskas,
och plattformen har redan lärt sig två gånger (#729, #760) att en identitet som
lades till för att få läsa också kunde skriva. Medgivandet ska därför ha
giltighetsintervall, omfattning och granskningsspår från första raden, och ligga
**vid sidan av** `patient_consents` — aldrig inuti, av samma skäl som
viljeyttringar hölls utanför den tabellen: ett anhörigprivilegium får inte
kunna förväxlas med ett sammanhållen-vård-medgivande.

---

## 1. Namnet — sist, eller inte alls

- **1.a Lägg till EPS som deklarerad förmåga, inte som nytt tjänstenamn.**
  En EPS-Composition-profil, en EPS-Bundle-ändpunkt och `eps` i
  CapabilityStatement.
  **Klart när:** tjänsten kan leverera ett EPS-paket **och** svarar oförändrat
  på varje anrop de elva syskontjänsterna gör i dag. Skälet står i bedömningen
  §1: ett giltigt EPS-dokument är också ett giltigt IPS-dokument, men inte
  tvärtom — så ett namnbyte hävdar den smalare av två sanna satser, och den
  bredare är den nio av elva konsumenter faktiskt vill.

- **1.b Pinna `COMPOSE_PROJECT_NAME` — oberoende av namnbytet.**
  Den är inte satt någonstans i repot, vilket verifierats. Behållarnamnen
  `ips-app-1` / `ips-db-1` betyder att projektet i dag är `ips`, så ett
  release-byte under ett opinnat projektnamn kan tyst skapa ett **andra**
  parallellt projekt med kolliderande portar. Det är formen på #113.
  **Klart när:** `docker-compose config` löser samma projektnamn från
  release-katalogen som från repots rot.

- **1.c Om namnet ändå måste bytas: efter fas 2 och 3, och av operatören.**
  `eps.pdhc.se` är ett nytt namn utan DNS-post, vhost eller certifikat, och
  `ips.pdhc.se` måste fortsätta svara eftersom 38 filer namnger det. Omvänd
  proxy är operatörens (CLAUDE.md §14, §15).
  **Rör inte volymen.** `pgdata` är `name: ips_pgdata`, `external: true` —
  compose äger den inte, så ett projektnamnsbyte kan inte göra den föräldralös.
  Att döpa om själva volymen betyder dump-och-återställ, och en kopiering i fel
  riktning mellan volymer förstörde en produktionsdatabas oåterkalleligt vid
  gateway→planp-bytet i mars 2026.
  **Klart när:** gamla namnet svarar fortfarande, nya namnet svarar, och
  `ips_pgdata` är orörd — verifierat, inte antaget.

---

## 2. EPS-konformitet — ett avslutningsjobb

Grunden finns: 2 795 rader i nio `euips_*`-moduler, en sektionskatalog, ett
dokumenthuvud, obligationsnivåer och en rapport. #791:s beslut att sektioner bor
i `fhir_resources` står oförändrat under EPS.

- **2.a Fyll de två LOINC-koder som repot vägrade gissa.**
  `euips_sections.py` lämnar en sektions LOINC som `None` snarare än att hitta
  på en. EPS-dokumentet levererar två av de tre: `alerts` = **104605-1**,
  `travel_history` = **10182-4**.
  **Klart när:** ett test låser varje kod till sin sektion och faller om någon
  av dem ändras. Det billigaste steget i hela planen, och det finns bara därför
  att koden vägrade gissa — ett gissat värde hade behövt letas upp och nystas
  tillbaka i stället.

- **2.b Två sektioner EPS har och vi saknar.**
  Patientens berättelse (**81338-6**) och Sjukdomshistoria (**11329-0**, unik
  för EPS). Båda är fritext i praktiken, så arbetet är katalogposter plus
  narrativ — inte terminologi.
  **Klart när:** båda finns i katalogen med sin LOINC och en patient kan få ett
  dokument som innehåller dem.

- **2.c Avgör nationellt kontra exporterat för två sektioner.**
  `past_illnesses` (**11348-0**) finns här men **profileras inte av EPS**.
  `patient_provided` har ingen EPS-motsvarighet alls.
  Rekommendation: behåll båda som nationella sektioner och mappa 11348-0 in i
  11329-0 först när ett EPS-dokument byggs för export. Ett giltigt EPS-dokument
  får inte bära dem; vår egen lagring får.
  **Klart när:** ett EPS-paket saknar båda, ett nationellt paket har dem, och
  samma data ligger bakom. Att bara släppa 11348-0 skulle göra kodade utläkta
  tillstånd till prosa — och katalogen varnar redan för att `problems` och
  `past_illnesses` skiljs **enbart** av `clinicalStatus`, så en slarvig
  sammanslagning lägger utläkta sjukdomar i den aktiva problemlistan.

- **2.d `devices` blir obligatorisk, och den har noll data.**
  EPS flyttar `procedures` (47519-4) och `devices` (46264-8) från
  rekommenderad till `1..1`. Repots egen katalogkommentar kallar den senare
  **"THE MISSING ONE"**: ingen `Device`-resurstyp finns i `fhir_resources` alls.
  #791:s absent-code-maskin hanterar redan fallet — `devices` har
  `absent_code="no-known-devices"` — så arbetet är att bära resurstyperna och
  generera den uttryckligen-tomma resursen.
  **Klart när:** varje patient har antingen en `DeviceUseStatement` eller en
  resurs som bär frånvarokoden, och **ingen** patient har en tom sektion.

- **2.d-ii Fyll sektion 46264-8 ur `alert.pdhc` i stället för ur en generator.**
  Sektionen är implantat, och alerts urval `Förekomst av implantat` är just den
  listan. `alert_assertion` bär `code_system` + `code` + `national_term`, vilket
  är vad en `DeviceUseStatement` behöver, och alerts steg 5.b projicerar redan
  mot ips.
  **Klart när:** ett implantat som registrerats i alert syns i patientens
  EPS-sektion 46264-8 utan att någon rör en generator. **Beror på** att alerts
  steg 5.a/5.b är byggt.

- **2.e R4-renderingsväg för EPS-export (beslut E1).**
  En serialiserare, och de elementskillnader som repot redan räknat upp.
  **Klart när:** ett EPS-paket validerar som R4 **och** tjänstens egen
  CapabilityStatement är oförändrat R5 — så ingen syskontjänst påverkas.

- **2.f Verifiera koderna mot den publicerade IG:n och vänd `CODES_VERIFIED`.**
  Koderna är skrivna ur kunskap om IG:n, inte ur en hämtning av den publicerade
  CodeSystem och ValueSet. EPS-dokumentet är dessutom ett **CI-bygge** av ett
  **STU 1 Ballot** — ett utkast av ett utkast.
  **Klart när:** varje kod är jämförd mot den publicerade källan och flaggan är
  vänd på ett ställe. **Till dess gäller den befintliga planens regel
  oförändrat: säg "alla obligatoriska sektioner finns", aldrig "EU-konform".**
  Kräver nätverksarbete som ingen beställt ännu.

### Vad fas 2 INTE innehåller

Tre mappningsskulder, och ingen av dem är ips-arbete: NPU → LOINC (lab),
KVÅ → SNOMED CT (åtgärder), NPL → ATC/EDQM/EMA SMS (läkemedel). De hör i
`termbank.pdhc` och `rosetta.pdhc`. Svensk källdata är till stor del fritext
eller NPU/KVÅ/NPL-kodad, och Snomed-införandet i Sverige är fortfarande
begränsat.

En notering mot `alert.pdhc`:s D1: den svenska Snomed-extensionens översatta
IPS-refset är det närmaste en svensk patientöversiktsvokabulär som finns, och
**licensen är gratis och utfärdas av Socialstyrelsen**. Det är en andra datapunkt
på den öppna frågan om vilken Snomed-licens som faktiskt innehas.

---

## 3. Patient-state med giltighetstid — ett nytt delsystem

Det här är den del ingen av de befintliga planerna rör. Kravet: allt
tillståndsbärande om en patient — adress, kontaktuppgift, anhörig inklusive
dennes åtkomstprivilegier, uppmärksamhetsinformation och annat — lagrat 1:1 på
patientkortet, medan transaktioner ligger i CDR, och med begynnelsedatum och
möjligt slutdatum.

**Hälften finns redan, och det är den svårare hälften.**
`fhir_service.update_resource()` uppdaterar inte: den skriver en ny rad med
`version_id + 1` och sätter den gamla till `superseded`. Registreringstiden är
alltså append-only. Vad som saknas är den andra axeln.

| axel | frågan den svarar på | status |
|---|---|---|
| registreringstid — `version_id`, `created_at` | när fick vi kännedom? | **byggd** |
| giltighetstid — början / möjligt slut | när var detta sant om patienten? | **saknas** |

Två axlar är ett **bitemporalt** lager, och paret är inte frivilligt här:
*"adressen var fel i registret mellan mars och juli"* kan inte uttryckas med en
axel, och det är normalfallet för en adress. Det är samma skillnad `alert.pdhc`
avgjorde som `asserted_at` mot `recorded_at` — vokabulären är redan
överenskommen i plattformen, den har bara inte nått ips.

- **3.a Namnge tillståndslagret — `ips_cards` är upptaget och betyder motsatsen.**
  `ips_cards` är 49 rader: `title`, `status`, `mode='full'` och en
  `snapshots`-relation. Det är ett **genererat dokument med versioner**, inte ett
  tillståndsregister. Ett kort i kravets mening är *den nuvarande sanningen om en
  person*; `ips_cards` är *en rendering gjord vid ett tillfälle*.
  **Klart när:** det nya namnet är valt och ingen läsare av schemat kan tro att
  de två är samma sak. Att återanvända namnet skulle göra varje läsare fel.

- **3.b Tillståndstabellen, append-only, med båda tidsaxlarna (beslut E2).**
  En rad per utsaga om ett tillstånd. `valid_from` obligatorisk, `valid_to`
  nullbar — frånvaro betyder *gäller fortfarande*, inte *okänt*. Registreringstid
  vid sidan av, aldrig sammanslagen.
  **Klart när:** ett försök att `UPDATE` en rad faller på en **databasspärr**,
  och frågan *vad gällde den 3 mars?* är samma fråga med ett annat datum.
  Mönstret finns färdigt i `alert.pdhc/app/models/assertion.py` — trigger i båda
  dialekterna, en källa delad av modellen och migreringen.

- **3.c Adress, kontaktuppgift och anhörig som riktiga element.**
  De finns inte i schemat alls; sökning på `address`, `telecom`, `contact`,
  `next_of_kin`, `anhörig` ger bara `audit_log.ip_address`, som är orelaterat.
  De finns bara inuti `fhir_resources.resource_json`, och bara därför att
  mockgeneratorn skriver dem — adressen som `city` + `country`, utan gata och
  utan postnummer.
  Anhörig finns som `RelatedPerson` plus en inbäddad `Patient.contact`-spegel,
  medvetet genererade ur en lista så att de inte kan säga emot varandra. Men den
  bär namn, relation och telefon — **inga privilegier, ingen giltighetstid,
  ingen identitet som kan autentiseras**.
  **Klart när:** en adress kan bäras med gata och postnummer och ett
  giltighetsintervall, och FHIR:s eget `Address.period` används i stället för ett
  eget fält.

- **3.c-ii Ge `patient_clinic_assignments` ett slutdatum.**
  Tabellen har `assigned_at` och ingenting mer: början utan slut. En patient som
  flyttar är därför antingen kvar på den gamla mottagningen eller har aldrig
  funnits där — och det är den tabellen `/api/v1/clinics/<guid>/patients` läser,
  rostret `sim.pdhc` bygger kohorter ur.
  **Klart när:** en avslutad koppling försvinner ur rostret men finns kvar i
  historiken, och de elva läsarna svarar oförändrat på en patient utan slutdatum.
  Additivt, nullbart, inget default — regeln tabellen hålls till.

- **3.d Identitet för en privatperson som inte är patienten (beslut E3).**
  `auth_service` känner `user_type == 'patient'`, så en patient kan
  autentisera sig. En anhörig kan inte: det finns ingen identitet för henne.
  Det är en `sso.pdhc`-fråga, inte en ips-fråga.
  **Klart när:** en anhörig kan autentisera sig som sig själv och inte som
  patienten. **Beror på `sso.pdhc`** och ligger utanför det här repot.

- **3.e Medgivandet och grenen i åtkomstpolicyn.**
  Ett tidsbegränsat, omfattningsbegränsat och granskningsbart medgivande från
  patienten till en namngiven privatperson, vid sidan av `patient_consents`.
  Och en ny gren i `care_access_policy.py` — den modul med störst
  spridningsyta i repot, läst av elva tjänster, och som i sin egen docstring
  kallar sig den enda källan till zonregeln *"så att inga två konsumenter kan
  tillämpa olika zonregler"*.
  **Klart när:** en anhörig med ett giltigt medgivande får läsa exakt det
  omfattningen säger och ingenting mer; ett **utgånget** medgivande nekas; och
  en kontroll som tar bort grenen gör att testet faller på sitt eget påstående.
  Nekandet måste bära ett eget skäl, inte återanvända ett vårdgrundsskäl, så att
  det går att skilja i granskningsloggen.

---

## 4. Ordning, och varför

**2 → 3 → 1.**

Fas 2 först därför att den är nästan klar och varje steg i den är additivt — den
kan levereras i småbitar utan att något syskon rör sig. Fas 3 därefter därför att
den är ett nytt delsystem som kräver tre beslut och berör den modul med störst
spridningsyta. Namnbytet sist, därför att det är det enda av de tre som inte kan
ångras härifrån och det enda som inte köper någon förmåga.

Ett undantag från ordningen: **1.b, att pinna `COMPOSE_PROJECT_NAME`, bör göras
nu.** Den är oberoende av namnbytet, den är en rättelse av en känd defektform
(#113), och den kostar ingenting.

Och **2.a bör göras i dag.** Två koder, ett test, en timme — och den enda
anledningen att den är så billig är att koden vägrade gissa.

---

## 5. Vad som inte är mätt

Angivet så att inget av det förväxlas med kontrollerat.

* **Den levande databasen.** Inga radantal, ingen kontroll av om någon patient
  faktiskt bär en adress i dag. Den befintliga planens fynd att 110 av 150
  patienter saknade kliniska resurser helt mättes 2026-10-07 och kan ha flyttat.
* **Servern.** Ingen `ssh`, ingen `docker inspect`. Compose-fyndet kommer ur
  repot och ur behållarnamnen i CLAUDE.md:s tabell, inte ur den körande
  plattformen. Att bekräfta det är en produktionsåtgärd.
* **Den publicerade EPS-IG:n.** Allt om EPS här kommer ur de två dokumenten i
  `docs/`, som själva är en läsning av ett CI-bygge av ett STU 1 Ballot.
  `CODES_VERIFIED` står kvar på `False`.
* **Om `patient_provided` och `past_illnesses` har EPS-hem jag inte funnit.**
  Sjutton sektioner jämfördes mot sjutton via LOINC. En sektion kan motsvara en
  annan semantiskt under en kod jag inte matchade.
* **`sso.pdhc`:s identitetsmodell**, som avgör merparten av E3:s kostnad.
