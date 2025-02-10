"""MQTT utilities and state management."""

import json

# Global MQTT client instance, to be set by code.py
mqtt_client = None

# MQTT topics
MQTT_TOPIC_STATE = "mr_tree/state"
MQTT_TOPIC_SET = "mr_tree/set"
MQTT_TOPIC_AVAILABILITY = "mr_tree/status"
MQTT_DISCOVERY_PREFIX = "homeassistant"
MQTT_DISCOVERY_TOPIC = f"{MQTT_DISCOVERY_PREFIX}/light/mr_tree/config"
MQTT_TIMER_STATE = "mr_tree/timer/state"
MQTT_TIMER_SET = "mr_tree/timer/set"
MQTT_TIMER_DISCOVERY_TOPIC = f"{MQTT_DISCOVERY_PREFIX}/sensor/mr_tree_timer/config"

def set_mqtt_client(client):
    """Set the global MQTT client instance.

    Args:
        client: The MQTT client instance from code.py
    """
    global mqtt_client
    mqtt_client = client

def publish_message(topic, message, retain=False):
    """Publish a message to MQTT.

    Args:
        topic: The MQTT topic to publish to
        message: The message to publish (will be converted to JSON if dict)
        retain: Whether to retain the message
    """
    if mqtt_client is None:
        print("Warning: MQTT client not initialized")
        return

    try:
        if isinstance(message, dict):
            message = json.dumps(message)
        mqtt_client.publish(topic, message, retain=retain)
    except Exception as e:
        print(f"Error publishing MQTT message: {e}")