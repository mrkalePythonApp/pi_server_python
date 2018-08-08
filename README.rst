****************
pi_server_python
****************

Python scripts in this set are designed as server applications intended to be
operated usually as system services or automatically started processes at
boot time of microcomputers.

All scripts should be considered as independent from each other, despite
the set seems like a package. However, for the sake of generating
the documentation with the system Sphinx, the repository might be handled
as a package.

All the scripts are aimed for Pi microcomputers running as headless servers,
e.g., ``Raspberry Pi``, ``Orange Pi``, ``Nano Pi``, etc.

The documentation to each module of the repository is located in the folder
`docs` and its subfolder `build` in form of an HTML site.


Scripts in repository
=====================

**server_fan**
  Script manages attached fan for cooling the system on the basis of
  the system temperature provided by the SoC. At the same time the script acts
  as a MQTT coordinator utilizing local MQTT broker ``mosquitto`` for data
  exchange. Script communicates with cloud services like ``ThingSpeak``
  and ``Blynk``.
