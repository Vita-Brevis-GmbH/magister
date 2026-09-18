# OCI-Abbild des Connector-Agenten (ADR-0014).
#
# Der Agent nimmt keine Verbindungen an, also EXPOSE nichts. Er läuft als
# unprivilegierter Benutzer und braucht nur ausgehend TCP 46200 sowie LDAPS
# ins eigene Netz.
FROM python:3.12-slim AS build
WORKDIR /src
# Der Agent benutzt die AD-Schicht von magister_api; seit ADR-0014 ist sie
# frei von FastAPI, das Abbild bleibt also klein.
COPY apps/api /src/apps/api
COPY agent /src/agent
RUN pip install --no-cache-dir --prefix=/install /src/apps/api /src/agent

FROM python:3.12-slim
RUN useradd --system --create-home --shell /usr/sbin/nologin magister-connector \
 && mkdir -p /var/lib/magister-connector \
 && chown magister-connector:magister-connector /var/lib/magister-connector \
 && chmod 700 /var/lib/magister-connector
COPY --from=build /install /usr/local
USER magister-connector
WORKDIR /var/lib/magister-connector
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["magister-connector", "--config", "/etc/magister-connector/config.json"]
CMD ["run"]
