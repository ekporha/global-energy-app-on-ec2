terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0" # Specify your desired AWS provider version
    }
  }
}

provider "aws" {
  region = "us-east-1"
  profile = "my-dev-profile" # Recommended: Use a named AWS CLI profile

}

# Define a security group for SSH and a VNC/RDP port (e.g., 5901 for VNC)
resource "aws_security_group" "app_sg" {
  name        = "global-energy-app-sg"
  description = "Allow SSH and VNC/RDP access to the application VM"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # WARNING: Broad access, restrict to your IP in production
  }

  ingress {
    from_port   = 5901 # Example VNC port, change for RDP or other GUI access
    to_port     = 5901
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # WARNING: Broad access, restrict to your IP in production
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# S3 Bucket for application files
resource "aws_s3_bucket" "app_files_bucket" {
  bucket = "your-unique-global-energy-app-bucket-replace-me" # <--- IMPORTANT: CHOOSE A GLOBALLY UNIQUE NAME
  acl    = "private" # Or "public-read" if you're comfortable, but private with IAM is more secure

  tags = {
    Name = "GlobalEnergyAppFiles"
  }
}

# Add an IAM Role and Instance Profile for your EC2 instance to access S3
resource "aws_iam_role" "ec2_s3_read_role" {
  name = "ec2_s3_read_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "ec2.amazonaws.com"
        },
      },
    ],
  })

  tags = {
    Name = "EC2S3ReadRole"
  }
}

resource "aws_iam_role_policy" "ec2_s3_read_policy" {
  name = "ec2_s3_read_policy"
  role = aws_iam_role.ec2_s3_read_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = [
          "s3:GetObject",
          "s3:ListBucket" # Required for aws s3 cp to list objects in the bucket
        ],
        Effect   = "Allow",
        Resource = [
          aws_s3_bucket.app_files_bucket.arn,
          "${aws_s3_bucket.app_files_bucket.arn}/*",
        ],
      },
    ],
  })
}

resource "aws_iam_instance_profile" "ec2_s3_read_profile" {
  name = "ec2_s3_read_profile"
  role = aws_iam_role.ec2_s3_read_role.name
}


# Define an EC2 instance
resource "aws_instance" "global_energy_app" { 
  ami           = "ami-0390c3f4e6b23f755"
  instance_type = "t2.medium"
  key_name      = "global-energy-app-key" 
  security_groups = [aws_security_group.app_sg.name]
  iam_instance_profile = aws_iam_instance_profile.ec2_s3_read_profile.name

  # User data script to set up the environment
  user_data = <<-EOF
    #!/bin/bash
    yum update -y # For Amazon Linux, use apt-get for Ubuntu
    yum install -y python3 python3-pip # Install Python and pip
    pip3 install reportlab PyPDF2 pycryptodome google-generativeai # Install Python dependencies

    # Create a directory for your application
    mkdir -p /opt/global_energy_app
    cd /opt/global_energy_app

    # Download application files from S3
    # IMPORTANT: Ensure your EC2 instance's IAM role has s3:GetObject permissions on the bucket.
    aws s3 cp s3://your-unique-global-energy-app-bucket-replace-me/app.py /opt/global_energy_app/app.py
    aws s3 cp s3://your-unique-global-energy-app-bucket-replace-me/encrypt_key.py /opt/global_energy_app/encrypt_key.py
    aws s3 cp s3://your-unique-global-energy-app-bucket-replace-me/encrypted_key.txt /opt/global_energy_app/encrypted_key.txt
    aws s3 cp s3://your-unique-global-energy-app-bucket-replace-me/global_energy_db.sqlite /opt/global_energy_app/global_energy_db.sqlite --no-guess-mime-type

    # Make scripts executable
    chmod +x /opt/global_energy_app/app.py
    chmod +x /opt/global_energy_app/encrypt_key.py

    # IMPORTANT: This setup is for a server where you might SSH in and run the GUI,
    # or set up a VNC server. Running a Tkinter GUI directly in user data won't
    # show a visible window without further configuration (like a display server).
    # If this is a server-side process, use nohup or a systemd service.
    # Example for background process (not for interactive GUI):
    # nohup python3 /opt/global_energy_app/app.py > /var/log/global_energy_app.log 2>&1 &
  EOF

  tags = {
    Name = "global-energy-app-vm"
  }
} # <--- UNCOMMENT THIS LINE (closing brace for aws_instance)