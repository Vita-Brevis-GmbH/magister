import enum

from sqlalchemy import Enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


#: Enum-Spalten speichern in SQLAlchemy standardmässig den **Namen** des
#: Members, nicht seinen Wert. Bei ``IsolationMode.schema_only = "schema"``
#: gehen die auseinander: die Anwendung schickt ``schema_only``, die Migration
#: hat ``schema`` angelegt — und jeder Kunden-Anlage endet im 500er.
#:
#: Aufgefallen erst beim Lauf gegen die echte, migrierte Datenbank: die Tests
#: bauten ihr Schema mit ``create_all``, und das erzeugt den Postgres-Typ aus
#: derselben falschen Annahme. Zwei Fehler, die sich gegenseitig verdecken.
#:
#: Mit ``values_callable`` wird überall der Wert gespeichert. Damit ist eine
#: künftige Abweichung zwischen Name und Wert harmlos, statt beim nächsten Mal
#: dieselbe halbe Stunde zu kosten.
def enum_column(enum_type: type[enum.Enum], *, name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])
