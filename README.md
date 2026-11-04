# Scale Up Vacation Tracker

A shared team calendar for holidays, company closures and time off. Team members request leave and track decisions. Administrators manage membership, review overlapping absences and approve or decline requests.

## Run locally

Install Docker Engine with Compose or Docker Desktop with Linux containers. From the project directory, copy the example configuration.

```sh
cp .env.example .env
```

In PowerShell, use `Copy-Item .env.example .env`. Generate two separate random values using the first command below. Save them in a password manager and set `SECRET_KEY` and `POSTGRES_PASSWORD` in `.env` before starting the services.

```sh
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d --build
docker compose logs web
docker compose exec web python manage.py createsuperuser
```

Open the [local app](http://localhost:8000) and sign in with your administrator account. Use **Team** to approve registrations or add members. To reset a password, run `docker compose exec web python manage.py changepassword USERNAME`.

The web service applies migrations at startup. Use `docker compose down` to stop the application and keep its named volumes. The `-v` option deletes those volumes.

## Using the calendar

- Select a date to see each absent member, their job role and the type of leave. Member and role filters persist when you change months.
- Choose **Request time off** and enter dates in DD.MM.YYYY format. Leave **To** blank for a single day. Ranges include weekends, holidays and both endpoints, up to 366 days.
- **New entry** records leave directly for selected members or all currently active accounts, including administrators. You can also create entry types and choose their colors.
- Approval and calendar entries are saved together. If a member already has an entry on an included date, the entire change is canceled. Only the first decision on a pending request is accepted.
- Archiving an account disables access and withdraws pending requests while preserving calendar entries and decision history.

## Deploy with HTTPS

1. Copy the repository to a Docker host and prepare `.env` as above. On Linux, restrict access with `chmod 600 .env`.
2. Point your domain to the server and open TCP ports 80 and 443 for Caddy and certificate issuance.
3. Set your domain in `.env` as shown below. Keep your existing secrets when upgrading.

```dotenv
DOMAIN=calendar.example.com
ALLOWED_HOSTS=calendar.example.com
HTTPS=1
```

4. Start the services. Create the first administrator if the database is new.

```sh
docker compose --profile https up -d --build
docker compose logs proxy web
docker compose exec web python manage.py createsuperuser
```

Share the HTTPS address with your team. Caddy obtains and renews certificates automatically. PostgreSQL runs on the Docker network and the web port binds to loopback. Set `TIME_ZONE` and run Compose with `up -d` to change the time zone.

## Back up and restore

Create a PostgreSQL custom-format backup. Choose a unique local filename for each backup.

```sh
docker compose exec -T db pg_dump -U kalendar -d kalendar -Fc -f /tmp/kalendar.dump
docker compose cp db:/tmp/kalendar.dump ./kalendar.dump
docker compose exec -T db rm /tmp/kalendar.dump
```

Keep the backup and configuration in a secure location outside the server. Test restoration in a separate Compose project first. The commands below replace the target database contents. Back up its current state and stop the web service before restoring.

```sh
docker compose stop web
docker compose cp ./kalendar.dump db:/tmp/restore.dump
docker compose exec -T db pg_restore --single-transaction --clean --if-exists --no-owner -U kalendar -d kalendar /tmp/restore.dump
docker compose exec -T db rm /tmp/restore.dump
docker compose start web
```

## Checks

```sh
docker compose exec web python manage.py check
docker compose exec web python manage.py test -v 2
```

The tests run against an isolated database. They cover registration, permissions, request privacy, approval, rejection, withdrawal, overlapping absences, calendar filters and custom entry types. To test without Docker, install Django 5.2 and tzdata, set `LOCAL_SQLITE=1` and a temporary `SECRET_KEY`, then run `python manage.py test`. Compose uses PostgreSQL by default.

