#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Central IoT server, fan manageer, and MQTT coordinator.

Script provides following functionalities:

- Script manages a fan attached to a GPIO pin for cooling the system
  on the basis of the system temperature provided by the SoC.
- Script acts as a MQTT coordinator utilizing local MQTT broker ``mosquitto``
  for data exchange within the script as well as with outside environment.
- Script communicates with cloud services ``ThingSpeak`` and ``Blynk``.
- Script publishes system temperature and fan status (running, idle) to all
  three platforms: ``local MQTT broker``, ``ThingSpeak cloud``, ``Blynk mobile
  application``.
- Script can receive commands from `local MQTT broker` and from
  `Blynk mobile app` in order to change its behaviour during runnig, e.g.,
  turn on or off the fan, change fan trigger temperatures, etc.

"""
__version__ = "0.4.0"
__status__ = "Beta"
__author__ = "Libor Gabaj"
__copyright__ = "Copyright 2018, " + __author__
__credits__ = [__author__]
__license__ = "MIT"
__maintainer__ = __author__
__email__ = "libor.gabaj@gmail.com"

# Standard library modules
import time
import os
import os.path
import sys
import argparse
import logging
# Third party modules
import BlynkLib as modBlynk
import gbj_pythonlib_sw.config as modConfig
import gbj_pythonlib_sw.mqtt as modMQTT
import gbj_pythonlib_sw.statfilter as modFilter
import gbj_pythonlib_sw.timer as modTimer
import gbj_pythonlib_sw.trigger as modTrigger
import gbj_pythonlib_hw.orangepi as modOrangePi


###############################################################################
# Script constants - General states and MQTT commands
###############################################################################
ON = "ON"
OFF = "OFF"
TOGGLE = "TOGGLE"
RESET = "RESET"


###############################################################################
# Script constants - Fan MQTT commands and maps
###############################################################################
CMD_FAN_ON = ON
CMD_FAN_OFF = OFF
CMD_FAN_TOGGLE = TOGGLE
CMD_FAN_PERCON = "PERCON"  # Percentage of maximal temperature for fan on
CMD_FAN_PERCOFF = "PERCOFF"  # Percentage of maximal temperature for fan off


###############################################################################
# Script constants - ThingSpeak statuses
###############################################################################
STATUS_FAN_ON = "FAN-ON"
STATUS_FAN_OFF = "FAN-OFF"


###############################################################################
# Script global variables
###############################################################################
script_run = True  # Flag about running script in a loop
cmdline = None  # Object with command line arguments
logger = None  # Object with standard logging
trigger = None  # Object with triggers
filter = None  # Object with statistical smoothing and filtering
config = None  # Object with MQTT configuration file processing
mqtt = None  # Object for MQTT broker manipulation
thingspeak = None  # Object for ThingSpeak MQTT manipulation
pi = None  # Object with OrangePi GPIO control
blynk = None  # Object for Blynk application cooperation


###############################################################################
# Helper functions
###############################################################################


###############################################################################
# General actions
###############################################################################
def action_fan(command, value=None):
    """Perform command for the fan.

    Arguments
    ---------
    command : str
        Action name to be realized.
    value
        Any value that the action should be realized with.

    """
    # Controlling fan
    if command in [CMD_FAN_ON, CMD_FAN_OFF, CMD_FAN_TOGGLE]:
        # Suppress publishing useless command, i.e., the command changes pin
        # state that it already has.
        try:
            if command == CMD_FAN_TOGGLE:
                if pi.is_pin_on(pi.PIN_FAN):
                    command = CMD_FAN_OFF
                else:
                    command = CMD_FAN_ON
            if command == CMD_FAN_ON:
                if pi.is_pin_on(pi.PIN_FAN):
                    return
                pi.pin_on(pi.PIN_FAN)
            elif command == CMD_FAN_OFF:
                if pi.is_pin_off(pi.PIN_FAN):
                    return
                pi.pin_off(pi.PIN_FAN)
            else:
                return
            logger.info("Fan set to %s", command)
        except Exception as errmsg:
            logger.error("Fan command %s failed: %s.", command, errmsg)
        # Publishing action
        mqtt_publish_fan()
        thingspeak_publish(fan_status=True)
        blynk_publish_fan_status()
    # Updating fan temperature percentages
    if command in [CMD_FAN_PERCON, CMD_FAN_PERCOFF]:
        try:
            value = abs(float(value))
            cmd_map = {CMD_FAN_PERCON: [{"fan_perc_on": value}, ON],
                       CMD_FAN_PERCOFF: [{"fan_perc_off": value}, OFF],
                       }
            setup_trigger_fan(**cmd_map[command][0])
            logger.info(
                "Updated fan limit %s to %s%%",
                cmd_map[command][1], value
            )
            blynk_publish_fan_limits()
        except Exception:
            logger.error("Fan command %s failed", command)
    # Updating fan temperature percentages
    if command == RESET:
        setup_trigger_fan(
            fan_perc_on=pi.FAN_PERC_ON_DEF,
            fan_perc_off=pi.FAN_PERC_OFF_DEF,
        )
        logger.info("Reset fan limits")
        blynk_publish_fan_limits()


def action_script(command):
    """Perform command for this script itself.

    Arguments
    ---------
    command : str
        Received command to be realized: ``{"EXIT"}``.

    """
    # Stop script
    if command == "EXIT":
        global script_run
        script_run = False


###############################################################################
# MQTT actions
###############################################################################
def mqtt_publish_temp():
    """Publish SoC temperature to a MQTT topic."""
    if not mqtt.get_connected():
        return
    message = filter.result()
    option = "server_data_temp"
    section = mqtt.GROUP_TOPICS
    try:
        mqtt.publish(message, option, section)
        logger.debug(
            "Published temperature %s°C to MQTT topic %s.",
            filter.result(), mqtt.topic_name(option, section))
    except Exception as errmsg:
        print "Libor - C"
        logger.error(
            "Temperature publishing to MQTT topic option %s:[%s] failed: %s.",
            option, section, errmsg)


def mqtt_publish_fan():
    """Publish fan state to the MQTT status topic."""
    if not mqtt.get_connected():
        return
    cfg_option = "server_status_fan"
    cfg_section = mqtt.GROUP_TOPICS
    if pi.is_pin_on(pi.PIN_FAN):
        message = STATUS_FAN_ON
    else:
        message = STATUS_FAN_OFF
    try:
        mqtt.publish(message, cfg_option, cfg_section)
        logger.debug(
            "Published fan status %s to MQTT topic %s.",
            message, mqtt.topic_name(cfg_option, cfg_section),
        )
    except Exception as errmsg:
        logger.error(
            "Publishing fan status %s to MQTT topic %s failed: %s.",
            message,
            mqtt.topic_name(cfg_option, cfg_section),
            errmsg,
        )


def mqtt_message_log(message):
    """Log receiving from a MQTT topic.

    Arguments
    ---------
    message : str
        An instance of ``MQTTMessage``.
        This is a class with members `topic`, `payload`, `qos`, `retain`.

    Returns
    -------
    bool
        Flag about present message payload.

    See Also
    --------
    gbj_pythonlib_sw.mqtt
        Module for MQTT processing.

    """
    logger.debug(
        "Message from MQTT topic %s with qos %s and retain %s",
        message.topic, message.qos, message.retain)
    if message.payload is None:
        return False
    logger.debug("%s: %s", sys._getframe(1).f_code.co_name, message.payload)
    return True


def thingspeak_publish(fan_status=False):
    """Publish to ThingSpeak.

    Arguments
    ---------
    fan_status : bool
        Flag determining whether current fan state should be published
        as a ThingSpeak channel status.

    Notes
    -----
    Data fields are published automatically.

    """
    fields = {thingspeak.FIELD_TEMP: filter.result()}
    # Changed fan state since recent publishing
    fan_state_cur = pi.pin_state(pi.PIN_FAN)
    if not hasattr(thingspeak, "fan_state_old"):
        thingspeak.fan_state_old = fan_state_cur
    if fan_state_cur != thingspeak.fan_state_old:
        fields[thingspeak.FIELD_FAN] = fan_state_cur
        logger.debug(
            "Fan state change %s -> %s for ThingSpeak field%s",
            thingspeak.fan_state_old, fan_state_cur, thingspeak.FIELD_FAN)
        thingspeak.fan_state_old = fan_state_cur
    # Fan status
    status = None
    if fan_status:
        if pi.is_pin_on(pi.PIN_FAN):
            status = STATUS_FAN_ON
        else:
            status = STATUS_FAN_OFF
        status += ": {}°C {}".format(
            fields[thingspeak.FIELD_TEMP],
            time.ctime()
            )
    # Publication to ThingSpeak
    try:
        logger.debug("Publish to ThingSpeak")
        if thingspeak.publish(fields=fields, status=status):
            logger.debug(
                "Published temperature %s°C to ThingSpeak field%s",
                fields[thingspeak.FIELD_TEMP], thingspeak.FIELD_TEMP)
            if thingspeak.FIELD_FAN in fields:
                logger.debug(
                    "Published fan state %s to ThingSpeak field%s",
                    fields[thingspeak.FIELD_FAN], thingspeak.FIELD_FAN)
            if status is not None and len(status) > 0:
                logger.debug(
                    "Published channel status %s to ThingSpeak",
                    status)
    except Exception as errmsg:
        logger.error(
            "Publishing to ThingSpeak failed: %s",
            errmsg)


def blynk_publish_temp():
    """Publish temperature to Blynk.

    Notes
    -----
    Particular mobile app widgets have to have reading frequency set to
    ``PUSH``.

    """
    global blynk
    blynk.virtual_write(blynk.VPIN_TEMP, filter.result())


def blynk_publish_fan_status():
    """Publish fan status to Blynk mobile application."""
    global blynk
    if blynk is None:
        return
    if pi.is_pin_on(pi.PIN_FAN):
        fan_status = ON
        led_value = 255
    else:
        fan_status = OFF
        led_value = 0
    try:
        blynk.virtual_write(blynk.VPIN_FAN_LED, led_value)
        logger.debug("Published fan status %s to Blynk.", fan_status)
    except Exception:
        logger.error("Publishing fan status to Blynk failed.")


def blynk_publish_fan_limits():
    """Publish fan temperature percentages to Blynk mobile application."""
    global blynk
    if blynk is None:
        return
    try:
        blynk.virtual_write(blynk.VPIN_FAN_PERCON, pi.FAN_PERC_ON_CUR)
        blynk.virtual_write(blynk.VPIN_FAN_PERCOFF, pi.FAN_PERC_OFF_CUR)
        logger.debug("Published fan percentages ON=%s%%, OFF=%s%% to Blynk.",
                     pi.FAN_PERC_ON_CUR, pi.FAN_PERC_OFF_CUR)
    except Exception:
        logger.error("Publishing fan percentages to Blynk failed.")


###############################################################################
# Callback functions
###############################################################################
def cbTimer_temp_measure(*arg, **kwargs):
    """Measure current CPU temperature."""
    # blynk_publish()
    exec_last = kwargs.pop("exec_last", False)
    logger.debug(
        "Measured temperature %s°C",
        filter.result(pi.measure_temperature())
    )
    if exec_last:
        # global script_run
        # script_run = False
        pass


def cbTimer_temp_publish(*arg, **kwargs):
    """Publish current CPU temperature."""
    logger.debug(
        "Publish temperature %s°C",
        filter.result()
    )
    mqtt_publish_temp()


def cbTimer_temp_triggers(*arg, **kwargs):
    """Execute CPU temperature triggers."""
    trigger.exec_triggers(filter.result(), ids=["fanon", "fanoff"])


def cbTimer_thingspeak(*arg, **kwargs):
    """Publish to ThingSpeak."""
    thingspeak_publish()


def cbTrigger_fan(*args, **kwargs):
    """Execute command for the fan."""
    command = kwargs.pop("cmd", None)
    if command is None:
        return
    action_fan(command)


def cbMqtt_on_connect(client, userdata, flags, rc):
    """Process actions when the broker responds to a connection request.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    flags : dict
        Response flags sent by the MQTT broker.
    rc : int
        The connection result (result code).

    See Also
    --------
    gbj_pythonlib_sw.mqtt._on_connect()
        Description of callback arguments for proper utilizing.

    """
    if rc == 0:
        logger.debug("Connected to %s: %s", str(mqtt), userdata)
        setup_mqtt_filters()
    else:
        logger.error("Connection to MQTT broker failed: %s", userdata)


def cbMqtt_on_disconnect(client, userdata, rc):
    """Process actions when the client disconnects from the broker.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    rc : int
        The connection result (result code).

    See Also
    --------
    gbj_pythonlib_sw.mqtt._on_connect()
        Description of callback arguments for proper utilizing.

    """
    logger.warning("Disconnected from %s: %s", str(mqtt), userdata)


def cbMqtt_on_subscribe(client, userdata, mid, granted_qos):
    """Process actions when the broker responds to a subscribe request.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    mid : int
        The message ID from the subscribe request.
    granted_qos : int
        The list of integers that give the QoS level the broker has granted
        for each of the different subscription requests.

    """
    # logger.debug("Subscribed to MQTT topic with message id %d", mid)
    pass


def cbMqtt_on_message(client, userdata, message):
    """Process actions when a non-filtered message has been received.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : object
        An instance of ``MQTTMessage``.
        This is a class with members `topic`, `payload`, `qos`, `retain`.

    Notes
    -----
    - The topic that the client subscribes to and the message does not match
      an existing topic filter callback.
    - Use message_callback_add() to define a callback that will be called for
      specific topic filters. This function serves as fallback when none
      topic filter matched.

    """
    if not mqtt_message_log(message):
        return


def cbMqtt_on_message_data(client, userdata, message):
    """Process server data send through a MQTT topic(s).

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : object
        An instance of ``MQTTMessage``.
        This is a class with members `topic`, `payload`, `qos`, `retain`.

    """
    if not mqtt_message_log(message):
        return
    # CPU Temperature
    if message.topic == mqtt.topic_name("server_data_temp"):
        value = float(message.payload)
        logger.debug("Received temperature %s°C", value)
    # Unexpected data
    else:
        logger.warning(
            "Received unknown data %s from topic %s",
            message.payload, message.topic)


def cbMqtt_on_message_command(client, userdata, message):
    """Process server command at receiving a message from the command topic(s).

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : object
        An instance of ``MQTTMessage``.
        This is a class with members `topic`, `payload`, `qos`, `retain`.

    Notes
    -----
    - The topic that the client subscribes to and the message match the topic
      filter for server commands.

    """
    if not mqtt_message_log(message):
        return
    # Command
    command = message.payload
    if message.topic == mqtt.topic_name("server_command"):
        logger.debug(
            "Received general command %s from topic %s",
            command, message.topic)
        action_script(command)
    # Test data
    elif message.topic == mqtt.topic_name("server_command_test"):
        logger.debug(
            "Received test command %s from topic %s",
            command, message.topic)
    # Fan control
    elif message.topic == mqtt.topic_name("server_command_fan"):
        logger.debug(
            "Received fan command %s from topic %s",
            command, message.topic)
        action_fan(command)
    elif message.topic in [mqtt.topic_name("server_command_fan_percon"),
                           mqtt.topic_name("server_command_fan_percoff"),
                           ]:
        command = message.topic.split("/").pop().upper()
        logger.debug(
            "Received fan command %s with value %s from topic %s",
            command, message.payload, message.topic)
        action_fan(command, message.payload)
    # Unexpected data
    else:
        logger.warning(
            "Received unknown command %s from topic %s",
            message.payload, message.topic)


###############################################################################
# Setup functions
###############################################################################
def setup_cmdline():
    """Define command line arguments."""
    config_file = os.path.splitext(os.path.abspath(__file__))[0] + ".ini"
    log_folder = "/var/log"

    parser = argparse.ArgumentParser(
        description="Tester, version " + __version__
    )
    # Position arguments
    parser.add_argument(
        "config",
        type=file,
        nargs="?",
        default=config_file,
        help="Configuration INI file, default: " + config_file
    )
    # Options
    parser.add_argument(
        "-V", "--version",
        action="version",
        version="%(prog)s " + __version__,
        help="Current version of the script."
    )
    parser.add_argument(
        "-v", "--verbose",
        choices=["debug", "warning", "info", "error", "critical"],
        default="warning",
        help="Level of logging to console."
    )
    parser.add_argument(
        "-l", "--loglevel",
        choices=["debug", "warning", "info", "error", "critical"],
        default="debug",
        help="Level of logging to log file."
    )
    parser.add_argument(
        "-d", "--logdir",
        default=log_folder,
        help="Folder of a log file, default " + log_folder
    )
    parser.add_argument(
        "-c", "--configuration",
        action="store_true",
        help="""Print configuration parameters in form of INI file content."""
    )
    # Process command line arguments
    global cmdline
    cmdline = parser.parse_args()


def setup_logger():
    """Configure logging facility."""
    global logger
    # Set logging to file for module and script logging
    log_file = "/".join([cmdline.logdir, os.path.basename(__file__) + ".log"])
    logging.basicConfig(
        level=getattr(logging, cmdline.loglevel.upper()),
        format="%(asctime)s - %(levelname)-8s - %(name)-20s: %(message)s",
        filename=log_file,
        filemode="w"
    )
    # Set console logging
    formatter = logging.Formatter(
        "%(levelname)-8s - %(name)-20s: %(message)s")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, cmdline.verbose.upper()))
    console_handler.setFormatter(formatter)
    logger = logging.getLogger("{} {}".format(
        os.path.basename(__file__), __version__))
    logger.addHandler(console_handler)
    logger.warning("Script started from file %s", os.path.abspath(__file__))


def setup_config():
    """Define configuration file management."""
    global config
    config = modConfig.Config(cmdline.config)
    # Print configuration file conten
    if cmdline.configuration:
        config.get_content()


def setup_pi():
    """Define GPIO control.

    Notes
    -----
    - Operational pin names are stored in the object as attributes.
    - Default fan percentage limits are stored in the object as attributes.

    """
    global pi
    pi = modOrangePi.OrangePiOne()
    pi.PIN_FAN = config.option("pin_fan_name", "Fan")
    # pi.PIN_LED = config.option("pin_led_name", "Fan")
    # Temperature percentage for fan ON
    pi.FAN_PERC_ON_DEF = abs(float(config.option(
        "percentage_maxtemp_on", "Fan", 85.0)))
    pi.FAN_PERC_ON_MIN = 80.0
    pi.FAN_PERC_ON_MAX = 95.0
    pi.FAN_PERC_ON_CUR = pi.FAN_PERC_ON_DEF
    # Temperature percentage for fan OFF
    pi.FAN_PERC_OFF_DEF = abs(float(config.option(
        "percentage_maxtemp_off", "Fan", 75.0)))
    pi.FAN_PERC_OFF_MIN = 60.0
    pi.FAN_PERC_OFF_MAX = 75.0
    pi.FAN_PERC_OFF_CUR = pi.FAN_PERC_OFF_DEF


def setup_mqtt():
    """Define MQTT management."""
    global mqtt
    mqtt = modMQTT.MqttBroker(config)
    mqtt.connect(
        username=config.option("username", mqtt.GROUP_BROKER),
        password=config.option("password", mqtt.GROUP_BROKER),
        connect=cbMqtt_on_connect,
        disconnect=cbMqtt_on_disconnect,
        subscribe=cbMqtt_on_subscribe,
        message=cbMqtt_on_message,
    )


def setup_mqtt_filters():
    """Define MQTT topic filters and subscribe to them.

    Notes
    -----
    - The function is called in on_connect callback function after successful
      connection to a MQTT broker.

    """
    mqtt.callback_filters(
        server_filter_data=cbMqtt_on_message_data,
        server_filter_command=cbMqtt_on_message_command,
    )
    try:
        mqtt.subscribe_filters()
    except Exception as errcode:
        logger.error(
            "MQTT subscribtion to topic filters failed with error code %s",
            errcode)


def setup_thingspeak():
    """Define ThingSpeak management."""
    global thingspeak
    thingspeak = modMQTT.ThingSpeak(config)
    thingspeak.FIELD_TEMP = int(config.option("field_temp",
                                              thingspeak.GROUP_BROKER, 1))
    thingspeak.FIELD_FAN = int(config.option("field_fan",
                                             thingspeak.GROUP_BROKER, 2))


def setup_filter():
    """Define statistical smoothing and filtering."""
    global filter
    filter = modFilter.StatFilterExponential(
        decimals=3,
        factor=0.2
    )
    # filter = gbj_statfilter.StatFilterRunning(
    #     decimals=3,
    #     stat_type=gbj_statfilter.MEDIAN,
    # )


def setup_trigger():
    """Define triggers for evaluating value limits."""
    global trigger
    trigger = modTrigger.Trigger()
    setup_trigger_fan()


def setup_trigger_fan(fan_perc_on=None, fan_perc_off=None):
    """Define triggers for controlling fan by SoC temperature.

    Arguments
    ---------
    fan_perc_on : float
        Percentage of maximal temperature for turning fan on.
    fan_perc_off : float
        Percentage of maximal temperature for turning fan off.

    """
    # Sanitize parameters
    pi.FAN_PERC_ON_CUR = max(min(float(fan_perc_on or pi.FAN_PERC_ON_CUR),
                                 pi.FAN_PERC_ON_MAX),
                             pi.FAN_PERC_ON_MIN)
    pi.FAN_PERC_OFF_CUR = max(min(float(fan_perc_off or pi.FAN_PERC_OFF_CUR),
                                  pi.FAN_PERC_OFF_MAX),
                              pi.FAN_PERC_OFF_MIN)
    if pi.FAN_PERC_OFF_CUR > pi.FAN_PERC_ON_CUR:
        p = pi.FAN_PERC_OFF_CUR
        pi.FAN_PERC_OFF_CUR = pi.FAN_PERC_ON_CUR
        pi.FAN_PERC_ON_CUR = p
    # Set triggers
    logger.debug(
        "Setup fan triggers: %s = %s%%, %s = %s%%",
        ON, pi.FAN_PERC_ON_CUR,
        OFF, pi.FAN_PERC_OFF_CUR)
    trigger.set_trigger(
        id="fanon",
        mode=modTrigger.UPPER,
        value=pi.convert_percentage_temperature(pi.FAN_PERC_ON_CUR),
        callback=cbTrigger_fan,
        cmd=CMD_FAN_ON,     # Arguments to callback
    )
    trigger.set_trigger(
        id="fanoff",
        mode=modTrigger.LOWER,
        value=pi.convert_percentage_temperature(pi.FAN_PERC_OFF_CUR),
        callback=cbTrigger_fan,
        cmd=CMD_FAN_OFF,     # Arguments to callback
    )


def setup_timers():
    """Define dictionary of timers."""
    # Timer 01
    name = "Timer_temp"
    cfg_section = "TimerTemperature"
    # Measurement period
    c_period = float(config.option("period_measure", cfg_section, 5.0))
    c_period = max(min(c_period, 60.0), 1.0)
    # Publishing prescale
    c_publish = int(config.option("prescale_publish", cfg_section, 3))
    c_publish = max(min(c_publish, 10), 1)
    # Trigger evaluation prescale
    c_triggers = int(config.option("prescale_triggers", cfg_section, 6))
    c_triggers = max(min(c_triggers, 1000), 1)
    logger.debug(
        "Setup timer %s: period = %ss, publish = %sx, triggers = %sx",
        name, c_period, c_publish, c_triggers)
    # Definition
    timer1 = modTimer.Timer(
        c_period,
        cbTimer_temp_measure,
        name=name,
        # count=9,
    )
    timer1.prescaler(c_publish, cbTimer_temp_publish)
    timer1.prescaler(c_triggers, cbTimer_temp_triggers)
    modTimer.register_timer(name, timer1)
    # Timer 02
    name = "Timer_thingspeak"
    cfg_section = thingspeak.GROUP_BROKER
    # Measurement period
    c_period = float(config.option("period_publish", cfg_section, 60.0))
    c_period = max(c_period, thingspeak.get_publish_delay())
    logger.debug(
        "Setup timer %s: period = %ss",
        name, c_period)
    # Definition
    timer2 = modTimer.Timer(
        c_period,
        cbTimer_thingspeak,
        name=name,
        # count=9,
    )
    modTimer.register_timer(name, timer2)
    # Start all timers
    modTimer.start_timers()


def setup_blynk():
    """Define Blynk parameters."""
    global blynk
    config_group = "Blynk"
    blynk = modBlynk.Blynk(config.option("blynk_auth", config_group))
    # Store Blynk colors
    blynk.COLOR_GREEN = "#23C48E"
    blynk.COLOR_BLUE = "#04C0F8"
    blynk.COLOR_YELLOW = "#ED9D00"
    blynk.COLOR_RED = "#D3435C"
    blynk.COLORDARK_BLUE = "#5F7CD8"
    # Store virtual pins
    blynk.VPIN_TEMP = abs(int(config.option("vpin_temp", config_group)))
    blynk.VPIN_FAN_LED = abs(int(config.option("vpin_fan_led", config_group)))
    blynk.VPIN_FAN_BTN = abs(int(config.option("vpin_fan_btn", config_group)))
    blynk.VPIN_FAN_PERCON = abs(int(config.option("vpin_fan_percon",
                                                  config_group)))
    blynk.VPIN_FAN_PERCOFF = abs(int(config.option("vpin_fan_percoff",
                                                   config_group)))

    @blynk.VIRTUAL_WRITE(blynk.VPIN_FAN_BTN)
    def blynk_fan_button(button_state):
        """Receive command for fan from mobile app.

        Arguments
        ---------
        button_state : str
            Received value from Blynk button widget.
        """
        # React only on pushing the button and ignore releasing it
        if int(button_state):
            logger.debug("Fan button state %s from Blynk virtual pin %s",
                         button_state, blynk.VPIN_FAN_BTN)
            action_fan(CMD_FAN_TOGGLE)

    @blynk.VIRTUAL_READ(blynk.VPIN_TEMP)
    def blynk_read_temperature():
        """Send data to mobile app on demand."""
        blynk.virtual_write(blynk.VPIN_TEMP, filter.result())

    @blynk.VIRTUAL_WRITE(blynk.VPIN_FAN_PERCON)
    def blynk_fan_percon(value):
        """Receive temperature percentage for fan ON from mobile app.

        Arguments
        ---------
        value : str
            Received percentage for fan ON value from Blynk numeric input
            widget.
        """
        # React only on pushing the button and ignore releasing it
        logger.debug("Fan ON percentage %s%% from Blynk virtual pin %s",
                     value, blynk.VPIN_FAN_PERCON)
        action_fan(CMD_FAN_PERCON, value)

    @blynk.VIRTUAL_WRITE(blynk.VPIN_FAN_PERCOFF)
    def blynk_fan_percoff(value):
        """Receive temperature percentage for fan OFF from mobile app.

        Arguments
        ---------
        value : str
            Received percentage for fan OFF value from Blynk numeric input
            widget.
        """
        # React only on pushing the button and ignore releasing it
        logger.debug("Fan OFF percentage %s%% from Blynk virtual pin %s",
                     value, blynk.VPIN_FAN_PERCOFF)
        action_fan(CMD_FAN_PERCOFF, value)


def setup():
    """Global initialization."""
    pass
    # Init Blynk mobile application
    # blynk_publish_temp() - Blynk reads temperature on it own
    blynk_publish_fan_status()
    blynk_publish_fan_limits()


def loop():
    """Wait for keyboard or system exit."""
    try:
        global blynk
        if blynk is None:
            logger.info("Script loop started")
            while (script_run):
                time.sleep(1)
            logger.warning("Script finished")
        else:
            logger.info("Script run by BLYNK")
            blynk.run()
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Script cancelled")
    finally:
        modTimer.stop_timers()


def main():
    """Fundamental control function."""
    setup_cmdline()
    setup_logger()
    setup_config()
    setup_pi()
    setup_mqtt()
    setup_thingspeak()
    setup_filter()
    setup_trigger()
    setup_timers()
    setup_blynk()
    setup()
    loop()


if __name__ == "__main__":
    if os.getegid() != 0:
        sys.exit('Script must be run as root')
    main()
