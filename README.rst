**********
server_fan
**********

Script manages attached fan for cooling the system on the basis of
the system temperature provided by the SoC_. At the same time the script acts
as an MQTT_ coordinator utilizing local MQTT broker ``mosquitto`` for data
exchange within IoT_. Script communicates with cloud services like
``ThingSpeak`` and ``Blynk``.

- For the sake of generating the documentation with the system ``Sphinx``,
  the repository might be handled as a package.

- The script is aimed for Pi microcomputers running as headless servers,
  e.g., ``Raspberry Pi``, ``Orange Pi``, ``Nano Pi``, etc.

- The documentation configuration for the script is located in the folder
  `docs/source`. The documentation in HTML_ format can be generated from
  the folder `docs` by the by command ``make html``.

- The script can run under ``Python2`` as well as ``Python3``.

.. [SoC] System on Chip
.. [MQTT] MQ Telemetry Transport
.. [IoT] Internet of Things
.. [HTML] Hyper Text Markup Language
