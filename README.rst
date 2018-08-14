**********
server_fan
**********

Script manages attached fan for cooling the system on the basis of
the system temperature provided by the SoC. At the same time the script acts
as a MQTT coordinator utilizing local MQTT broker ``mosquitto`` for data
exchange within IoT. Script communicates with cloud services like
``ThingSpeak`` and ``Blynk``.

- For the sake of generating the documentation with the system Sphinx,
  the repository might be handled as a package.

- The script is aimed for Pi microcomputers running as headless servers,
  e.g., ``Raspberry Pi``, ``Orange Pi``, ``Nano Pi``, etc.

- The documentation configuration for the script is located in the folder
  `docs/source`. The documentation in HTML format can be generated from
  the folder `docs` by the by command ``make html``.

- The script can run under ``Python2`` as well as ``Python3``.
