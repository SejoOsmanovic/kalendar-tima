# Kalendar tima

Interna Django aplikacija sa PostgreSQL bazom. Tim koristi jedan URL, a svaki član ima zaseban nalog. Administrator upravlja članovima i unosima, vidi preklapanja i odlučuje o zahtjevima. Radnik vidi zajednički kalendar i svoje zahtjeve.

## Lokalno pokretanje

Potrebni su Docker Engine sa dodatkom Compose ili Docker Desktop u režimu Linux kontejnera. U direktorijumu repozitorijuma kopirajte primjer konfiguracije.

```sh
cp .env.example .env
```

U PowerShellu koristite `Copy-Item .env.example .env`. U datoteku `.env` unesite različite slučajno generisane vrijednosti za `SECRET_KEY` i `POSTGRES_PASSWORD`. Za svaku pokrenite sljedeću komandu jednom i sačuvajte rezultat u upravitelju lozinki.

```sh
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d --build
docker compose logs web
docker compose exec web python manage.py createsuperuser
```

Otvorite [lokalnu aplikaciju](http://localhost:8000) i prijavite se kreiranim nalogom. U meniju **Tim** dodajte radnike i dodatne administratore. Lozinku za svakog člana dostavite privatno. Lozinka postojećeg naloga može se promijeniti komandom `docker compose exec web python manage.py changepassword KORISNIK`.

Migracije se primjenjuju pri pokretanju web servisa. `docker compose down` zaustavlja aplikaciju i čuva podatke u imenovanom volumenu. Opcija `-v` briše volumene.

## Rad sa kalendarom

- Klik na datum otvara dnevni pregled. Filter po radniku važi i pri prelasku na drugi mjesec.
- **Traži slobodno** otvara zahtjev za izabrani datum. Za jedan dan polje **Do** ostaje prazno. Period uključuje oba krajnja datuma, vikende i praznike, najviše 366 dana po unosu.
- **Novi unos** odmah evidentira datume za izabrane osobe ili sve trenutno aktivne naloge, uključujući administratore. Naknadno dodavanje radnika ne mijenja prethodne unose.
- Odobravanje i upis odsustva čine jednu transakciju. Ako bilo koji datum već ima unos za istu osobu, cijela izmjena se poništava. Pri suprotstavljenim odlukama prolazi samo prva promjena statusa sa čekanja.
- Arhiviranje ukida pristup, povlači zahtjeve na čekanju i zadržava evidentirana odsustva i istoriju odluka.

## Postavljanje na server sa HTTPS-om

1. Na serveru sa Dockerom smjestite repozitorijum i pripremite `.env` kao gore. Ograničite pristup toj datoteci, na Linuxu komandom `chmod 600 .env`.
2. Usmjerite DNS zapis domena, npr. `kalendar.firma.ba`, na IP adresu servera. Otvorite TCP portove 80 i 443 za Caddy i pribavljanje TLS certifikata.
3. Postavite sljedeće vrijednosti u `.env`, koristeći svoj stvarni domen. Zadržite iste tajne pri nadogradnjama.

```dotenv
DOMAIN=kalendar.firma.ba
ALLOWED_HOSTS=kalendar.firma.ba
HTTPS=1
```

4. Pokrenite servise i napravite prvog administratora ako je baza nova.

```sh
docker compose --profile https up -d --build
docker compose logs proxy web
docker compose exec web python manage.py createsuperuser
```

Zaposlenima podijelite HTTPS adresu svog domena. Caddy automatski pribavlja i obnavlja certifikat. PostgreSQL je dostupan unutar Docker mreže, a direktni port aplikacije vezan je za loopback. Za promjenu vremenske zone podesite `TIME_ZONE` i ponovo pokrenite Compose sa `up -d`.

## Rezervna kopija i vraćanje

Napravite kopiju baze u prilagođenom PostgreSQL formatu. Koristite jedinstveno ime datoteke za svaku kopiju.

```sh
docker compose exec -T db pg_dump -U kalendar -d kalendar -Fc -f /tmp/kalendar.dump
docker compose cp db:/tmp/kalendar.dump ./kalendar.dump
docker compose exec -T db rm /tmp/kalendar.dump
```

Sačuvajte kopiju i konfiguraciju na zaštićenoj lokaciji izvan servera. Vraćanje prvo provjerite u zasebnom Compose projektu. Sljedeće komande zamjenjuju sadržaj ciljne baze. Zaustavite web servis i prethodno napravite kopiju trenutnog stanja.

```sh
docker compose stop web
docker compose cp ./kalendar.dump db:/tmp/restore.dump
docker compose exec -T db pg_restore --single-transaction --clean --if-exists --no-owner -U kalendar -d kalendar /tmp/restore.dump
docker compose exec -T db rm /tmp/restore.dump
docker compose start web
```

## Provjere

```sh
docker compose exec web python manage.py check
docker compose exec web python manage.py test -v 2
```

Testovi koriste izdvojenu testnu bazu. Prijavljuju Anu, Marka i dva administratora. Provjeravaju petak 06.11.2026, vidljivost napomene, Markov odmor, Anino odobrenje, drugu odluku nad istim zahtjevom, odbijanje, povlačenje, neovlašćen pristup, filtriranje, arhiviranje i poništavanje konfliktnog višednevnog unosa. Za brzu provjeru bez Dockera instalirajte Django 5.2 i tzdata, postavite `LOCAL_SQLITE=1` i privremeni `SECRET_KEY`, pa pokrenite `python manage.py test`. Podrazumijevana Compose konfiguracija koristi PostgreSQL.

