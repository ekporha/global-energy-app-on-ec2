Part 1: Comprehensive Procedural Steps: Deploying a Python Tkinter GUI App to AWS EC2 via VNC
This guide covers setting up your AWS infrastructure with Terraform, deploying your Python Tkinter application to an EC2 instance, and accessing its GUI remotely using VNC.

Phase 1: Local Setup & Project Preparation
Prerequisites (Ensure these are installed on your local machine):

AWS Account & CLI: Configured with administrative access.

Terraform: Download and install the Terraform CLI.

Git (Optional): For version control.

Python 3 & Pip: For developing and managing Python dependencies.

PuTTY or OpenSSH Client: For SSH access to EC2 (OpenSSH is built into Windows 10/11 CMD/PowerShell).

VNC Client: (e.g., TightVNC Viewer, RealVNC Viewer) for connecting to the GUI.

Project Files:

Create a local directory for your project (e.g., global_energy_app_deployment).

Place your application files in this directory:

main.tf (your Terraform configuration)

app.py (your Tkinter application)

encrypt_key.py

encrypted_key.txt

global_energy_db.sqlite

Generate SSH Key Pair:

If you don't have one, create an EC2-compatible .pem key pair:

AWS Console: Go to EC2 -> Key Pairs -> Create Key Pair. Name it (e.g., global-energy-app-key), select .pem format, and download it.

Local Machine: Store this .pem file securely (e.g., C:\Users\YourUser\Downloads\global-energy-app-key.pem).

Set Permissions (Windows CMD/PowerShell): Right-click .pem file -> Properties -> Security tab -> Advanced -> Disable inheritance -> Convert inherited permissions -> Remove all users/groups except your own user (ensure only "Read" access for your user).

Phase 2: Terraform Deployment
Initialize Terraform:

Open Command Prompt (CMD) or PowerShell in your project directory.

Bash

  terraform init
Plan the Deployment (Optional, but recommended):

Bash

  terraform plan
Review the planned changes.

Deploy Infrastructure:

Bash

  terraform apply
Type yes when prompted to confirm.

![image](https://github.com/user-attachments/assets/11435e1f-90bb-43e8-ac56-a1ce1aa6d0d3)


Important: Note down the aws_s3_bucket.app_bucket.id (your S3 bucket name) from the Terraform output. This is crucial for the next step. Also, note the aws_instance.global_energy_app.public_ip or aws_instance.global_energy_app.public_dns for SSH/VNC connection later.

Upload Application Files to S3 Bucket:

Go to your AWS S3 Console.

Find the S3 bucket created by Terraform (its name will be in the Terraform output, e.g., your-unique-global-energy-app-bucket).

Click on the bucket name.

Click "Upload", then "Add files".

Select app.py, encrypt_key.py, encrypted_key.txt, and global_energy_db.sqlite from your local project directory.

Click "Upload".

(Reason for this step: The EC2 user_data script retrieves these from S3 during instance launch. If terraform apply completed but these files weren't uploaded, the EC2 instance wouldn't find them, causing issues as experienced during troubleshooting).

If you uploaded files after terraform apply for the EC2 instance, you will need to re-deploy just the EC2 instance for the user_data script to run again:

Bash

terraform destroy -target=aws_instance.global_energy_app
terraform apply
Phase 3: EC2 Instance Configuration & VNC Setup
Connect to EC2 Instance via SSH:

Open CMD/PowerShell.

Bash

  ssh -i "PATH_TO_YOUR_KEY.pem" ec2-user@YOUR_EC2_PUBLIC_IP
Replace PATH_TO_YOUR_KEY.pem (e.g., "C:\Users\YourUser\Downloads\global-energy-app-key.pem") and YOUR_EC2_PUBLIC_IP (e.g., 54.123.45.67).

Type yes if prompted to confirm authenticity.

![image](https://github.com/user-attachments/assets/c4dbb82c-b35e-4b67-b035-94597593741f)


Verify Application Files (Optional, but good check):

Bash

  ls -l /opt/global_energy_app/
You should see app.py, encrypt_key.py, encrypted_key.txt, global_energy_db.sqlite.

Install Essential Packages (on EC2 instance):

Install nano (friendly text editor):

Bash

sudo yum install -y nano
Install Xorg, GNOME session, and TigerVNC for Amazon Linux 2023:

Bash

sudo yum update -y
sudo yum install -y xorg-x11-server-Xorg xorg-x11-xinit gnome-session-xsession tigervnc-server xterm
(This specifically installs the X server, minimal GNOME session components to get an X session, TigerVNC server, and the xterm terminal).

Configure VNC Server xstartup:

Create the VNC configuration directory:

Bash

mkdir -p ~/.vnc
Edit the xstartup file:

Bash

nano ~/.vnc/xstartup
Paste the following content exactly:

Bash

#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec gnome-session
Save and exit nano (Ctrl+X, then Y, then Enter).

Make the script executable:

Bash

chmod +x ~/.vnc/xstartup
Set Your VNC Password:

Bash

  vncpasswd
Enter your desired VNC password. You can decline the "view-only" password.

Manage and Start VNC Server:

Kill any old/stuck VNC sessions (if any):

Bash

vncserver -kill :1
(Ignore "command not found" or "Can't find file..." messages if it wasn't running).

Start the VNC Server:

Bash

vncserver :1
Confirm you see the New 'X' desktop is ...:1 message.

Verify Security Group (Already in Terraform, but Double-Check):

Ensure your EC2 instance's Security Group (created by Terraform) has an Inbound Rule allowing TCP traffic on port 5901.

The source should be your public IP address (My IP) for security, or 0.0.0.0/0 (Anywhere) for broad testing (less secure).

(This was typically handled by your main.tf during terraform apply, but manually verify in AWS EC2 Console -> Security Groups if you still get "connection actively refused").

Phase 4: Connect to GUI & Run Application
Connect from Local VNC Client:

Open your VNC Client (e.g., TightVNC Viewer) on your local Windows machine.

In the connection field, enter your EC2 instance's Public IPv4 address followed by :1 (e.g., 54.123.45.67:1).

Enter your VNC password when prompted.

You should now see a GNOME desktop (likely a basic version) with an xterm terminal window.

Run Your Python Application:

Within the VNC session, use the xterm terminal window.

Navigate to your application directory:

Bash

cd /opt/global_energy_app
Run your Python application:

Bash

python3 app.py
If you encounter ModuleNotFoundError: No module named 'tkinter', install it:

Bash

sudo yum install -y python3-tkinter
Then retry python3 app.py.

If other ModuleNotFoundError occur (e.g., for reportlab, PyPDF2, google.generativeai, pycryptodome), install them:

Bash

pip3 install reportlab PyPDF2 google-generativeai pycryptodome
Then retry python3 app.py.

Your Python Tkinter GUI application should now be running in the VNC session!

![image](https://github.com/user-attachments/assets/83686027-6699-4681-bdc4-02ae10131ca7)


Phase 5: Cleanup (Important!)
To avoid unexpected AWS charges, remember to destroy your infrastructure when you are finished using it.

In your project directory on your local machine:

Bash

terraform destroy
Type yes when prompted.
