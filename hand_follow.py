import socket
import json
import time
import threading

from kortex_api.autogen.client_stubs.BaseClientRpc import BaseClient
from kortex_api.autogen.messages import Base_pb2
from kortex_api.TCPTransport import TCPTransport
from kortex_api.RouterClient import RouterClient
from kortex_api.SessionManager import SessionManager
from kortex_api.autogen.messages import Session_pb2


# SETTINGS
ROBOT_IP = "xxx.xxx.xx.x"
ROBOT_USERNAME = "your-username"
ROBOT_PASSWORD = "your-password"
UDP_PORT = 9000 

MAX_SPEED = 0.2   # m/s - START LOW
GAIN = 0.8        # proportional gain - START LOW

# Workspace bounds in ROBOT coordinates (meters from robot base)
# Robot will refuse to move outside this box
BOUNDS = {
    "x_min": 0.1,  "x_max": 0.9,
    "y_min": -0.4, "y_max": 0.4,
    "z_min": 0.1,  "z_max": 0.9,
}

# CONNECT TO ROBOT

print("=" * 50)
print("KINOVA HAND FOLLOWER - SAFETY STARTUP")
print("=" * 50)
print(f"\nConnecting to robot at {ROBOT_IP}...")

try:
    transport = TCPTransport()
    transport.connect(ROBOT_IP, 10000)
except Exception as e:
    print(f"\n*** FAILED TO CONNECT: {e}")
    print("Check that:")
    print("  - Robot is powered on (green LED)")
    print("  - Ethernet cable is connected")
    print("  - Your computer IP is 192.168.1.XX")
    input("\nPress Enter to exit...")
    exit()

router = RouterClient(transport, lambda e: print(f"Comms error: {e}"))

session_info = Session_pb2.CreateSessionInfo()
session_info.username = ROBOT_USERNAME
session_info.password = ROBOT_PASSWORD
session_info.session_inactivity_timeout = 60000
session_info.connection_inactivity_timeout = 2000

try:
    session_manager = SessionManager(router)
    session_manager.CreateSession(session_info)
except Exception as e:
    print(f"\n*** LOGIN FAILED: {e}")
    print("Check username/password")
    transport.disconnect()
    input("\nPress Enter to exit...")
    exit()

base_client = BaseClient(router)
print("Connected and logged in!\n")

# STEP 1: SHOW ROBOT STATE
# this is a safety check you can skip if you want 
print("-" * 50)
print("STEP 1: ROBOT STATUS CHECK")
print("-" * 50)

try:
    feedback = base_client.GetMeasuredCartesianPose()
    print(f"\nRobot end effector position (meters):")
    print(f"  X: {feedback.x:.4f}")
    print(f"  Y: {feedback.y:.4f}")
    print(f"  Z: {feedback.z:.4f}")
    print(f"  Theta X: {feedback.theta_x:.2f}")
    print(f"  Theta Y: {feedback.theta_y:.2f}")
    print(f"  Theta Z: {feedback.theta_z:.2f}")
except Exception as e:
    print(f"\n*** COULD NOT READ ROBOT POSITION: {e}")
    print("The robot may be in a fault state. Check the web app.")
    session_manager.CloseSession()
    transport.disconnect()
    input("\nPress Enter to exit...")
    exit()

print(f"\nWorkspace bounds set to:")
print(f"  X: [{BOUNDS['x_min']}, {BOUNDS['x_max']}] m")
print(f"  Y: [{BOUNDS['y_min']}, {BOUNDS['y_max']}] m")
print(f"  Z: [{BOUNDS['z_min']}, {BOUNDS['z_max']}] m")

input("\nPress Enter to continue to UDP check...")


# STEP 2: CHECK TOUCHDESIGNER DATA
# checks data is coming in from touchdesigner
print("\n" + "-" * 50)
print("STEP 2: TOUCHDESIGNER DATA CHECK")
print("-" * 50)
print("\nListening for hand data from TouchDesigner on port", UDP_PORT)
print("Make sure TD is running and move your hand around.")
print("Waiting for data...\n")

test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
test_sock.settimeout(10)
test_sock.bind(("127.0.0.1", UDP_PORT))

try:
    data, addr = test_sock.recvfrom(1024)
    pos = json.loads(data.decode())
    print(f"Receiving data! First packet:")
    print(f"  X: {pos['x']:.4f} cm")
    print(f"  Y: {pos['y']:.4f} cm")
    print(f"  Z: {pos['z']:.4f} cm")
except socket.timeout:
    print("*** NO DATA received from TouchDesigner after 10 seconds.")
    print("Check that:")
    print("  - TD is running")
    print("  - CHOP Execute DAT is cooking")
    print("  - Port matches (should be", UDP_PORT, ")")
    test_sock.close()
    session_manager.CloseSession()
    transport.disconnect()
    input("\nPress Enter to exit...")
    exit()

# Show a few seconds of data so you can see the range
print("\nStreaming values for 5 seconds so you can check the range...")
print("Move your hand to the extremes of your tracking area.\n")

min_vals = {"x": float('inf'), "y": float('inf'), "z": float('inf')}
max_vals = {"x": float('-inf'), "y": float('-inf'), "z": float('-inf')}
start = time.time()

while time.time() - start < 5:
    try:
        data, addr = test_sock.recvfrom(1024)
        pos = json.loads(data.decode())
        for axis in ["x", "y", "z"]:
            min_vals[axis] = min(min_vals[axis], pos[axis])
            max_vals[axis] = max(max_vals[axis], pos[axis])
        print(f"  X: {pos['x']:>8.3f}  Y: {pos['y']:>8.3f}  Z: {pos['z']:>8.3f} cm", end="\r")
    except socket.timeout:
        pass

test_sock.close()

print(f"\n\nObserved ranges from your hand movement:")
print(f"  X: [{min_vals['x']:.3f}, {max_vals['x']:.3f}] cm")
print(f"  Y: [{min_vals['y']:.3f}, {max_vals['y']:.3f}] cm")
print(f"  Z: [{min_vals['z']:.3f}, {max_vals['z']:.3f}] cm")

input("\nPress Enter to continue to nudge test...")

# STEP 3: NUDGE TEST
# safety check - can change nudge distance or speed if you want 
print("\n" + "-" * 50)
print("STEP 3: NUDGE TEST")
print("-" * 50)
print("\nThis will move the robot a TINY amount in each axis")
print("so you can verify the directions are correct.")
print("\n*** HAND ON E-STOP ***")

nudge_distance = 0.02  # 2cm
nudge_speed = 0.05     # very slow

for axis_name, axis_index in [("X", "x"), ("Y", "y"), ("Z", "z")]:
    input(f"\nPress Enter to nudge +{axis_name} by {nudge_distance*100:.0f}cm (then back)...")
    
    # Nudge positive
    command = Base_pb2.TwistCommand()
    setattr(command.twist, f"linear_{axis_index}", nudge_speed)
    command.duration = 0
    base_client.SendTwistCommand(command)
    time.sleep(nudge_distance / nudge_speed)
    base_client.Stop()
    time.sleep(0.5)
    
    # Nudge back
    command = Base_pb2.TwistCommand()
    setattr(command.twist, f"linear_{axis_index}", -nudge_speed)
    command.duration = 0
    base_client.SendTwistCommand(command)
    time.sleep(nudge_distance / nudge_speed)
    base_client.Stop()
    time.sleep(0.5)
    
    print(f"  Did the robot move in the direction you expected for +{axis_name}?")
    print(f"  If not, we need to flip or swap axes in the mapping.")

input("\nAll axes tested. Press Enter to start hand following...")

# STEP 4: LIVE HAND FOLLOWING
# the final frontier, the future! this step is operating the robot with yr bod. 
print("\n" + "-" * 50)
print("STEP 4: LIVE FOLLOWING")
print("-" * 50)
print(f"Max speed: {MAX_SPEED} m/s")
print(f"Gain: {GAIN}")
print("Press Ctrl+C to stop at any time.\n")

latest_position = {"x": 0.0, "y": 0.0, "z": 0.0}
position_lock = threading.Lock()

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", UDP_PORT))
    while True:
        data, addr = sock.recvfrom(1024)
        try:
            pos = json.loads(data.decode())
            with position_lock:
                latest_position["x"] = pos["x"]
                latest_position["y"] = pos["y"]
                latest_position["z"] = pos["z"]
        except:
            pass

listener_thread = threading.Thread(target=udp_listener, daemon=True)
listener_thread.start()

def clamp(value, min_val, max_val):
    return max(min_val, min(max_val, value))

try:
    # Capture the robot's starting position as the center point
    # Hand at (0,0,0) = robot stays here. Hand movement offsets from here.
    feedback = base_client.GetMeasuredCartesianPose()
    center_x = feedback.x
    center_y = feedback.y
    center_z = feedback.z
    print(f"Center point set to: ({center_x:.3f}, {center_y:.3f}, {center_z:.3f})")
    print("Hand data will offset from this position.\n")

    loop_count = 0
    while True:
        with position_lock:
            # Hand data is in cm. Convert to meters and add to center point.
            # Axis mapping: Kinect Z -> Robot X, Kinect X -> Robot Y, Kinect Y -> Robot Z
            target_x = center_x + (latest_position["z"] / 100.0)
            target_y = center_y + (latest_position["x"] / 100.0)
            target_z = center_z + (latest_position["y"] / 100.0)

        # Clamp target to workspace bounds
        target_x = clamp(target_x, BOUNDS["x_min"], BOUNDS["x_max"])
        target_y = clamp(target_y, BOUNDS["y_min"], BOUNDS["y_max"])
        target_z = clamp(target_z, BOUNDS["z_min"], BOUNDS["z_max"])

        # Get current robot position
        feedback = base_client.GetMeasuredCartesianPose()
        current_x = feedback.x
        current_y = feedback.y
        current_z = feedback.z

        # Proportional control: velocity = error * gain
        vel_x = clamp((target_x - current_x) * GAIN, -MAX_SPEED, MAX_SPEED)
        vel_y = clamp((target_y - current_y) * GAIN, -MAX_SPEED, MAX_SPEED)
        vel_z = clamp((target_z - current_z) * GAIN, -MAX_SPEED, MAX_SPEED)

        # Send velocity command (same structure as nudge test)
        command = Base_pb2.TwistCommand()
        command.twist.linear_x = vel_x
        command.twist.linear_y = vel_y
        command.twist.linear_z = vel_z
        command.twist.angular_x = 0.0
        command.twist.angular_y = 0.0
        command.twist.angular_z = 0.0
        command.duration = 0
        base_client.SendTwistCommand(command)

        # Print status every 20 loops (~once per second)
        loop_count += 1
        if loop_count % 20 == 0:
            print(f"Target: ({target_x:.3f}, {target_y:.3f}, {target_z:.3f})  "
                  f"Robot: ({current_x:.3f}, {current_y:.3f}, {current_z:.3f})  "
                  f"Vel: ({vel_x:.3f}, {vel_y:.3f}, {vel_z:.3f})")

        time.sleep(0.05)

except KeyboardInterrupt:
    print("\n\nStopping robot...")
    base_client.Stop()
    print("Robot stopped.")

finally:
    session_manager.CloseSession()
    transport.disconnect()
    print("Disconnected. Done.")