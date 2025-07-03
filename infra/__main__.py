import pulumi
import pulumi_aws as aws
import json

# Configuration
config = pulumi.Config()
app_name = config.get("appName") or "job-queue-system"
environment = config.get("environment") or "dev"
aws_region = config.get("awsRegion") or "us-east-1"
vpc_cidr = config.get("vpcCidr") or "10.0.0.0/16"
key_name = config.get("keyName") or "job-queue-key"

# VPC
vpc = aws.ec2.Vpc(
    f"{app_name}-vpc",
    cidr_block=vpc_cidr,
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={
        "Name": f"{app_name}-vpc-{environment}",
        "Environment": environment,
    },
)

# Subnets - 1 public, 1 private
public_subnet = aws.ec2.Subnet(
    f"{app_name}-public-subnet",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    availability_zone=f"{aws_region}a",
    map_public_ip_on_launch=True,
    tags={
        "Name": f"{app_name}-public-subnet-{environment}",
        "Environment": environment,
    },
)

private_subnet = aws.ec2.Subnet(
    f"{app_name}-private-subnet",
    vpc_id=vpc.id,
    cidr_block="10.0.2.0/24",
    availability_zone=f"{aws_region}b",
    tags={
        "Name": f"{app_name}-private-subnet-{environment}",
        "Environment": environment,
    },
)

# IGW
internet_gateway = aws.ec2.InternetGateway(
    f"{app_name}-igw",
    vpc_id=vpc.id,
    tags={
        "Name": f"{app_name}-igw-{environment}",
        "Environment": environment,
    },
)

# NAT Gateway (using EC2 NAT instance instead of managed NAT Gateway to stay in free tier)
# Find Ubuntu AMI for NAT instance
nat_ami = aws.ec2.get_ami(
    most_recent=True,
    owners=["099720109477"],  # Canonical
    filters=[
        aws.ec2.GetAmiFilterArgs(
            name="name",
            values=["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"],
        ),
        aws.ec2.GetAmiFilterArgs(
            name="virtualization-type",
            values=["hvm"],
        ),
    ],
)

# Security group for NAT instance
nat_sg = aws.ec2.SecurityGroup(
    f"{app_name}-nat-sg",
    vpc_id=vpc.id,
    description="Security group for NAT instance",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=[vpc_cidr],
            description="Allow all traffic from VPC",
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
            description="Allow all outbound traffic",
        ),
    ],
    tags={
        "Name": f"{app_name}-nat-sg-{environment}",
        "Environment": environment,
    },
)

# NAT instance
nat_instance = aws.ec2.Instance(
    f"{app_name}-nat-instance",
    ami=nat_ami.id,
    instance_type="t2.micro",  # Free tier eligible
    subnet_id=public_subnet.id,
    vpc_security_group_ids=[nat_sg.id],
    source_dest_check=False,  # Required for NAT functionality
    tags={
        "Name": f"{app_name}-nat-instance-{environment}",
        "Environment": environment,
    },
    user_data="""#!/bin/bash
# Enable IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward
# Setup NAT
apt-get update -y
apt-get install -y iptables-persistent
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
netfilter-persistent save
""",
)

# Route Tables - 1 public, 1 private
public_route_table = aws.ec2.RouteTable(
    f"{app_name}-public-rt",
    vpc_id=vpc.id,
    routes=[
        aws.ec2.RouteTableRouteArgs(
            cidr_block="0.0.0.0/0",
            gateway_id=internet_gateway.id,
        ),
    ],
    tags={
        "Name": f"{app_name}-public-rt-{environment}",
        "Environment": environment,
    },
)

private_route_table = aws.ec2.RouteTable(
    f"{app_name}-private-rt",
    vpc_id=vpc.id,
    routes=[
        aws.ec2.RouteTableRouteArgs(
            cidr_block="0.0.0.0/0",
            instance_id=nat_instance.id,
        ),
    ],
    tags={
        "Name": f"{app_name}-private-rt-{environment}",
        "Environment": environment,
    },
)

# Route table associations
public_rt_association = aws.ec2.RouteTableAssociation(
    f"{app_name}-public-rt-assoc",
    subnet_id=public_subnet.id,
    route_table_id=public_route_table.id,
)

private_rt_association = aws.ec2.RouteTableAssociation(
    f"{app_name}-private-rt-assoc",
    subnet_id=private_subnet.id,
    route_table_id=private_route_table.id,
)

# Security Groups
api_sg = aws.ec2.SecurityGroup(
    f"{app_name}-api-sg",
    vpc_id=vpc.id,
    description="Security group for API server",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=22,
            to_port=22,
            cidr_blocks=["0.0.0.0/0"],
            description="SSH access",
        ),
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=8000,
            to_port=8000,
            cidr_blocks=["0.0.0.0/0"],
            description="API access",
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        ),
    ],
    tags={
        "Name": f"{app_name}-api-sg-{environment}",
        "Environment": environment,
    },
)

worker_sg = aws.ec2.SecurityGroup(
    f"{app_name}-worker-sg",
    vpc_id=vpc.id,
    description="Security group for worker server",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=22,
            to_port=22,
            cidr_blocks=["0.0.0.0/0"],
            description="SSH access",
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        ),
    ],
    tags={
        "Name": f"{app_name}-worker-sg-{environment}",
        "Environment": environment,
    },
)

monitor_sg = aws.ec2.SecurityGroup(
    f"{app_name}-monitor-sg",
    vpc_id=vpc.id,
    description="Security group for monitor server",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=22,
            to_port=22,
            cidr_blocks=["0.0.0.0/0"],
            description="SSH access",
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        ),
    ],
    tags={
        "Name": f"{app_name}-monitor-sg-{environment}",
        "Environment": environment,
    },
)

redis_sg = aws.ec2.SecurityGroup(
    f"{app_name}-redis-sg",
    vpc_id=vpc.id,
    description="Security group for Redis",
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=6379,
            to_port=6379,
            security_groups=[api_sg.id, worker_sg.id, monitor_sg.id],
            description="Redis access",
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        ),
    ],
    tags={
        "Name": f"{app_name}-redis-sg-{environment}",
        "Environment": environment,
    },
)

# IAM role for EC2 instances
instance_role = aws.iam.Role(
    f"{app_name}-ec2-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Action": "sts:AssumeRole",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Effect": "Allow",
            "Sid": ""
        }]
    }),
    tags={
        "Name": f"{app_name}-ec2-role-{environment}",
        "Environment": environment,
    },
)

# Add permissions for autoscaling to the monitor service
monitor_policy = aws.iam.Policy(
    f"{app_name}-monitor-policy",
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "autoscaling:DescribeAutoScalingGroups",
                    "autoscaling:SetDesiredCapacity"
                ],
                "Resource": "*"
            }
        ]
    })
)

monitor_policy_attachment = aws.iam.RolePolicyAttachment(
    f"{app_name}-monitor-policy-attachment",
    role=instance_role.name,
    policy_arn=monitor_policy.arn
)

# Attach SSM policy for easier management
ssm_policy_attachment = aws.iam.RolePolicyAttachment(
    f"{app_name}-ssm-policy",
    role=instance_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
)

# Create instance profile
instance_profile = aws.iam.InstanceProfile(
    f"{app_name}-instance-profile",
    role=instance_role.name,
)

# Find latest Ubuntu AMI for EC2 instances
ec2_ami = aws.ec2.get_ami(
    most_recent=True,
    owners=["099720109477"],  # Canonical
    filters=[
        aws.ec2.GetAmiFilterArgs(
            name="name",
            values=["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"],
        ),
        aws.ec2.GetAmiFilterArgs(
            name="virtualization-type",
            values=["hvm"],
        ),
    ],
)

# Redis - Using EC2 instance with Redis instead of ElastiCache to stay in free tier
redis_instance = aws.ec2.Instance(
    f"{app_name}-redis",
    ami=ec2_ami.id,
    instance_type="t2.micro",  # Free tier eligible
    subnet_id=private_subnet.id,
    vpc_security_group_ids=[redis_sg.id],
    key_name=key_name,
    iam_instance_profile=instance_profile.name,
    user_data="""#!/bin/bash
apt-get update -y
apt-get install -y redis-server
# Configure Redis to listen on all interfaces
sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
# Disable protected mode
sed -i 's/protected-mode yes/protected-mode no/' /etc/redis/redis.conf
# Restart Redis to apply changes
systemctl restart redis-server
""",
    tags={
        "Name": f"{app_name}-redis-{environment}",
        "Environment": environment,
    },
)

# API EC2 instance
api_user_data = pulumi.Output.all(redis_instance.private_ip).apply(
    lambda args: f"""#!/bin/bash
apt-get update -y
apt-get install -y python3-pip git
pip3 install fastapi uvicorn redis
git clone https://github.com/yourusername/job-queue-system.git /app
cd /app
# Set environment variables
cat > /etc/profile.d/job_queue_env.sh << 'EOL'
export REDIS_HOST="{args[0]}"
export REDIS_PORT=6379
export QUEUE_NAME="job_queue"
export RUNNING_IN_CLOUD=true
EOL
chmod +x /etc/profile.d/job_queue_env.sh
source /etc/profile.d/job_queue_env.sh
# Start the API server
cd /app
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 &
# Add to startup
echo "@reboot cd /app && source /etc/profile.d/job_queue_env.sh && nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 &" | crontab -
"""
)

api_instance = aws.ec2.Instance(
    f"{app_name}-api",
    ami=ec2_ami.id,
    instance_type="t2.micro",  # Free tier eligible
    subnet_id=public_subnet.id,
    vpc_security_group_ids=[api_sg.id],
    key_name=key_name,
    iam_instance_profile=instance_profile.name,
    user_data=api_user_data,
    tags={
        "Name": f"{app_name}-api-{environment}",
        "Environment": environment,
    },
)

# Worker EC2 instance
worker_user_data = pulumi.Output.all(redis_instance.private_ip).apply(
    lambda args: f"""#!/bin/bash
apt-get update -y
apt-get install -y python3-pip git
pip3 install redis
git clone https://github.com/yourusername/job-queue-system.git /app
cd /app
# Set environment variables
cat > /etc/profile.d/job_queue_env.sh << 'EOL'
export REDIS_HOST="{args[0]}"
export REDIS_PORT=6379
export QUEUE_NAME="job_queue"
export RUNNING_IN_CLOUD=true
EOL
chmod +x /etc/profile.d/job_queue_env.sh
source /etc/profile.d/job_queue_env.sh
# Start the worker
cd /app
nohup python3 -m app.worker &
# Add to startup
echo "@reboot cd /app && source /etc/profile.d/job_queue_env.sh && python3 -m app.worker" | crontab -
"""
)

worker_instance = aws.ec2.Instance(
    f"{app_name}-worker",
    ami=ec2_ami.id,
    instance_type="t2.micro",  # Free tier eligible
    subnet_id=private_subnet.id,
    vpc_security_group_ids=[worker_sg.id],
    key_name=key_name,
    iam_instance_profile=instance_profile.name,
    user_data=worker_user_data,
    tags={
        "Name": f"{app_name}-worker-{environment}",
        "Environment": environment,
    },
)

# Monitor EC2 instance
monitor_user_data = pulumi.Output.all(redis_instance.private_ip).apply(
    lambda args: f"""#!/bin/bash
apt-get update -y
apt-get install -y python3-pip git
pip3 install redis aioboto3
git clone https://github.com/yourusername/job-queue-system.git /app
cd /app
# Set environment variables
cat > /etc/profile.d/job_queue_env.sh << 'EOL'
export REDIS_HOST="{args[0]}"
export REDIS_PORT=6379
export QUEUE_NAME="job_queue"
export RUNNING_IN_CLOUD=true
export AWS_REGION="{aws_region}"
EOL
chmod +x /etc/profile.d/job_queue_env.sh
source /etc/profile.d/job_queue_env.sh
# Start the monitor
cd /app
nohup python3 -m app.monitor &
# Add to startup
echo "@reboot cd /app && source /etc/profile.d/job_queue_env.sh && python3 -m app.monitor" | crontab -
"""
)

monitor_instance = aws.ec2.Instance(
    f"{app_name}-monitor",
    ami=ec2_ami.id,
    instance_type="t2.micro",  # Free tier eligible
    subnet_id=private_subnet.id,
    vpc_security_group_ids=[monitor_sg.id],
    key_name=key_name,
    iam_instance_profile=instance_profile.name,
    user_data=monitor_user_data,
    tags={
        "Name": f"{app_name}-monitor-{environment}",
        "Environment": environment,
    },
)

# Outputs
pulumi.export("vpc_id", vpc.id)
pulumi.export("public_subnet_id", public_subnet.id)
pulumi.export("private_subnet_id", private_subnet.id)
pulumi.export("api_instance_public_ip", api_instance.public_ip)
pulumi.export("api_instance_private_ip", api_instance.private_ip)
pulumi.export("worker_instance_private_ip", worker_instance.private_ip)
pulumi.export("monitor_instance_private_ip", monitor_instance.private_ip)
pulumi.export("redis_instance_private_ip", redis_instance.private_ip)
