# ADR 0006 · Un paquete Python `avia/` en vez de `services/*` separados

**Contexto.** §6 sugería `services/api`, `services/scheduler`, `services/bank-connectors`, etc.
**Decisión.** Un solo paquete (`avia.api`, `avia.scheduler`, `avia.connectors`, `avia.engine`) y un solo proceso.
**Motivo.** El scheduler y la API comparten el motor y el lock de PostgreSQL. Separarlos en procesos agregaba
coordinación sin beneficio en un NAS de un solo usuario. Los nombres con guion (`bank-connectors`) no son
importables en Python. Si hiciera falta escalar, `avia.scheduler` puede correr como proceso propio sin cambios en el motor.
