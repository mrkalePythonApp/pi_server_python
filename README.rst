**********
server_fan
**********

Script manages attached fan for cooling the system on the basis of
the system temperature provided by the SoC [1]_. At the same time the script acts
as an MQTT [2]_ coordinator utilizing local MQTT broker ``mosquitto`` for data
exchange within IoT [3]_. Script communicates with cloud services like
``ThingSpeak`` and ``Blynk``.

- For the sake of generating the documentation with the system ``Sphinx``,
  the repository might be handled as a package.

- The script is aimed for Pi microcomputers running as headless servers,
  e.g., ``Raspberry Pi``, ``Orange Pi``, ``Nano Pi``, etc.

- The documentation configuration for the script is located in the folder
  `docs/source`. The documentation can be generated from the folder `docs`
  in HTML [4]_ format by the command ``make html`` and in PDF [5]_ format
  by the command ``make latexpdf``.

- The generated documentation of the script is published on the dedicated
  Github page `server_fan <https://mrkalepythonapp.github.io/server_fan/>`_.

- The script can run under ``Python2`` as well as ``Python3``. However, it is
  defaulted to Python3 by the `shebang`.

- It is recommended to run the **script as a service** of the operating system.

- All relevant parameters for the script are located in the configuration INI
  file. It contains sensitive data as well, like passwords and access tokens to
  servers and clouds. So that the repository contains just the sample INI file
  with placeholders instead of real such as sensitive data. The production INI
  file should be present only and only in some trusted locality with root
  access, e.g., in the folder ``/usr/local/etc`` in order not to be exposed to
  regular users.

.. [1] System on Chip
.. [2] MQ Telemetry Transport
.. [3] Internet of Things
.. [4] Hyper Text Markup Language
.. [5] Portable Document Format
