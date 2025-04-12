import pulumi
import pulumi_aws as aws
import json
import os

if not os.path.exists("index.template.html"):
	raise FileNotFoundError("Missing 'index.template.html'. Please add it to your project directory.")

# ==============================
# CONFIGURATION
# ==============================

config = pulumi.Config()
env = config.require("environment")
# Prefix for 'prod' or 'dev' environment
STACK_PREFIX = "" if env == 'prod' else f"{env}-"
CUSTOM_STAGE = env # 'prod' or 'dev' or anything else
VPC_CIDR = "10.0.0.0/16"

region = aws.config.region
db_username = config.require("dbUsername")
db_password = config.require_secret("dbPassword")

# ==============================
# VPC
# ==============================
# Create VPC
vpc = aws.ec2.Vpc("custom-vpc",
	cidr_block=VPC_CIDR,
	enable_dns_support=True,
	enable_dns_hostnames=True,
	tags={"Name": "pulumi-vpc"}
)

# Create Internet Gateway
igw = aws.ec2.InternetGateway("vpc-igw",
	vpc_id=vpc.id,
	tags={"Name": "pulumi-igw"}
)

# Create Public Subnets
public_subnet_1 = aws.ec2.Subnet("public-subnet-1",
	vpc_id=vpc.id,
	cidr_block="10.0.1.0/24",
	availability_zone="ap-southeast-1a",
	map_public_ip_on_launch=True,
	tags={"Name": "public-subnet-1"}
)

public_subnet_2 = aws.ec2.Subnet("public-subnet-2",
	vpc_id=vpc.id,
	cidr_block="10.0.2.0/24",
	availability_zone="ap-southeast-1b",
	map_public_ip_on_launch=True,
	tags={"Name": "public-subnet-2"}
)

# Public Route Table
public_rt = aws.ec2.RouteTable("public-rt",
	vpc_id=vpc.id,
	routes=[{
		"cidr_block": "0.0.0.0/0",
		"gateway_id": igw.id
	}],
	tags={"Name": "public-rt"}
)

# Associate public subnets with route table
aws.ec2.RouteTableAssociation("public-rt-assoc-1",
	subnet_id=public_subnet_1.id,
	route_table_id=public_rt.id
)

aws.ec2.RouteTableAssociation("public-rt-assoc-2",
	subnet_id=public_subnet_2.id,
	route_table_id=public_rt.id
)

# Create Private Subnets
private_subnet_1 = aws.ec2.Subnet("private-subnet-1",
	vpc_id=vpc.id,
	cidr_block="10.0.3.0/24",
	availability_zone="ap-southeast-1a",
	map_public_ip_on_launch=False,
	tags={"Name": "private-subnet-1"}
)

private_subnet_2 = aws.ec2.Subnet("private-subnet-2",
	vpc_id=vpc.id,
	cidr_block="10.0.4.0/24",
	availability_zone="ap-southeast-1b",
	map_public_ip_on_launch=False,
	tags={"Name": "private-subnet-2"}
)



# ==============================
# SECURITY GROUPS & VPC
# ==============================

lambda_sg = aws.ec2.SecurityGroup("lambda-sg",
	vpc_id=vpc.id,
	description="Allow Lambda to connect to RDS and Secret Manager Endpoint",
	ingress=[{
		"protocol": "tcp",
		"from_port": 5432,
		"to_port": 5432,
		"security_groups": [],
	}],
	egress=[{
		"protocol": "-1",
		"from_port": 0,
		"to_port": 0,
		"cidr_blocks": ["0.0.0.0/0"],
	}]
)

rds_sg = aws.ec2.SecurityGroup("rds-sg",
	vpc_id=vpc.id,
	description="Allow RDS access from Lambda",
	ingress=[{
		"protocol": "tcp",
		"from_port": 5432,
		"to_port": 5432,
		"security_groups": [lambda_sg.id]
	}],
	egress=[{
		"protocol": "-1",
		"from_port": 0,
		"to_port": 0,
		"cidr_blocks": ["0.0.0.0/0"],
	}]
)

# ==============================
# RDS INSTANCE
# ==============================

subnet_group = aws.rds.SubnetGroup("rds-subnet-group",
	subnet_ids=[private_subnet_1, private_subnet_2],
	tags={"Name": "rds-subnet-group"}
)

rds_param_group = aws.rds.ParameterGroup("rds-custom-pg",
	family="postgres17",
	description="Custom parameter group with rds.force_ssl disabled",
	parameters=[
		aws.rds.ParameterGroupParameterArgs(
			name="rds.force_ssl",
			value="0",
		),
	]
)

db_instance = aws.rds.Instance("mydb",
	engine="postgres",
	instance_class="db.t3.micro",
	allocated_storage=20,
	db_name="mydatabase",
	db_subnet_group_name=subnet_group.name,
	vpc_security_group_ids=[rds_sg.id],
	username=db_username,
	password=db_password,
	parameter_group_name=rds_param_group,
	skip_final_snapshot=True,
	apply_immediately=True
)

# ==============================
# SECRETS MANAGER
# ==============================

db_secret = aws.secretsmanager.Secret("db-credentials")

secret_value = aws.secretsmanager.SecretVersion("db-credentials-version",
	secret_id=db_secret.id,
	secret_string=pulumi.Output.all(
		db_password, db_instance.address, db_instance.port, db_instance.db_name
	).apply(lambda args: json.dumps({
		"username": db_username,
		"password": args[0],
		"host": args[1],
		"port": args[2],
		"dbname": args[3]
	}))
)

# ==============================
# IAM ROLE for LAMBDA
# ==============================

lambda_role = aws.iam.Role("lambda-role",
	assume_role_policy=json.dumps({
		"Version": "2012-10-17",
		"Statement": [{
			"Effect": "Allow",
			"Principal": {"Service": "lambda.amazonaws.com"},
			"Action": "sts:AssumeRole"
		}]
	})
)

aws.iam.RolePolicyAttachment("lambda-basic-execution",
	role=lambda_role.name,
	policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)

aws.iam.RolePolicyAttachment("lambda-secrets-access",
	role=lambda_role.name,
	policy_arn="arn:aws:iam::aws:policy/SecretsManagerReadWrite"
)

aws.iam.RolePolicyAttachment("lambda-vpc-access",
	role=lambda_role.name,
	policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
)

# ==============================
# VPC ENDPOINT FOR SECRETS MANAGER
# ==============================
secretsmanager_endpoint_sg = aws.ec2.SecurityGroup("secretsmanager-endpoint-sg",
	vpc_id=vpc.id,
	description="Allow traffic to Secrets Manager Endpoint from Lambda",
	ingress=[{
		"protocol": "tcp",
		"from_port": 443, # HTTPS port
		"to_port": 443, # HTTPS port
		"security_groups": [lambda_sg.id], # Allow from Lambda SG
	}],
	egress=[{
		"protocol": "-1",
		"from_port": 0,
		"to_port": 0,
		"cidr_blocks": ["0.0.0.0/0"], # Allow all outbound (can be restricted if needed)
	}]
)

secretsmanager_endpoint = aws.ec2.VpcEndpoint("secretsmanager-endpoint",
	vpc_id=vpc.id,
	service_name=f"com.amazonaws.{region}.secretsmanager", # Service name for Secrets Manager in your region
	vpc_endpoint_type="Interface", # Interface endpoint is needed for Secrets Manager
	subnet_ids=[private_subnet_1.id, private_subnet_2.id],
	security_group_ids=[secretsmanager_endpoint_sg.id], # Use dedicated SG for endpoint
	private_dns_enabled=True # Recommended for easier access within VPC
)


# ==============================
# LAMBDA FUNCTION
# ==============================

lambda_function = aws.lambda_.Function("api-lambda",
	role=lambda_role.arn,
	runtime="nodejs18.x",
	handler="index.handler",
	timeout=10,
	code=pulumi.AssetArchive({
		".": pulumi.FileArchive("./lambda")
	}),
	vpc_config=aws.lambda_.FunctionVpcConfigArgs(
		subnet_ids=[private_subnet_1],
		security_group_ids=[lambda_sg.id]
	),
	environment=aws.lambda_.FunctionEnvironmentArgs(
		variables={
			"SECRET_ARN": db_secret.arn
		}
	)
)

# ==============================
# API GATEWAY
# It has a little bit difficulty for me to config them
# Refer https://github.com/pulumi/examples/blob/master/aws-py-apigateway-lambda-serverless/__main__.py
# to make it easier
# ==============================

# Create a single Swagger spec route handler for a Lambda function.
def swagger_route_handler(arn):
	return {
		"x-amazon-apigateway-any-method": {
			"x-amazon-apigateway-integration": {
				"uri": pulumi.Output.format(
					"arn:aws:apigateway:{0}:lambda:path/2015-03-31/functions/{1}/invocations",
					region,
					arn,
				),
				"passthroughBehavior": "when_no_match",
				"httpMethod": "POST",
				"type": "aws_proxy",
			},
		},
	}

# Create the API Gateway Rest API, using a swagger spec.
rest_api = aws.apigateway.RestApi(
	"rest-api",
	body=pulumi.Output.json_dumps(
		{
			"swagger": "2.0",
			"info": {"title": "My API", "version": "1.0"},
			"paths": {
				"/{proxy+}": swagger_route_handler(lambda_function.arn),
			},
		}
	),
)

# Create a deployment of the Rest API.
deployment = aws.apigateway.Deployment(
	"rest-api-deployment",
	rest_api=rest_api.id,
	# Note: Set to empty to avoid creating an implicit stage, we'll create it
	# explicitly below instead.
	stage_name="",
)

# Create a stage, which is an addressable instance of the Rest API. Set it to point at the latest deployment.
stage = aws.apigateway.Stage(
	"rest-api-stage",
	rest_api=rest_api.id,
	deployment=deployment.id,
	stage_name=CUSTOM_STAGE,
)

# Give permissions from API Gateway to invoke the Lambda
rest_invoke_permission = aws.lambda_.Permission(
	"rest-api-lambda-permission",
	action="lambda:InvokeFunction",
	function=lambda_function.name,
	principal="apigateway.amazonaws.com",
	source_arn=stage.execution_arn.apply(lambda arn: arn + "/*"),
)

# ==============================
# S3 Bucket
# ==============================
# Create an AWS resource (S3 Bucket)
bucket = aws.s3.Bucket(
	f"{STACK_PREFIX}my-bucket",
	# bucket=f"{STACK_PREFIX}my-bucket",
	website={
		"index_document": "index.html",
	}
)

ownership_controls = aws.s3.BucketOwnershipControls(
	'ownership-controls',
	bucket=bucket.id,
	rule={
		"object_ownership": 'ObjectWriter',
	},
)

public_access_block = aws.s3.BucketPublicAccessBlock(
	'public-access-block', bucket=bucket.id, block_public_acls=False
)

bucket_object = aws.s3.BucketObject(
	'index.html',
	bucket=bucket.id,
	source=pulumi.FileAsset('index.html'),
	content_type='text/html',
	acl='public-read',
	opts=pulumi.ResourceOptions(depends_on=[public_access_block, ownership_controls]),
)

# ==============================
# OUTPUT & HTML INJECTION
# ==============================

api_url = pulumi.Output.concat(
	"https://", rest_api.id, ".execute-api.", aws.config.region, ".amazonaws.com/", stage.stage_name, "/data"
)

def inject_api_url(url: str):
	with open("index.template.html", "r") as f:
		html = f.read()
	html = html.replace("API_GATEWAY_URL", url)
	with open("index.html", "w") as f:
		f.write(html)

api_url.apply(lambda url: inject_api_url(url))
final_index_object = pulumi.Output.all(api_url).apply(lambda args: (
	inject_api_url(args[0]),
	# Upload final index.html to S3
	aws.s3.BucketObject(
		"index.html",
		bucket=bucket.id,
		source=pulumi.FileAsset("index.html"),
		content_type="text/html"
	)
))[1]  # only keep the BucketObject from tuple


# ==============================
# OUTPUTS
# ==============================

pulumi.export("api_url", api_url)
pulumi.export("rds_endpoint", db_instance.endpoint.apply(lambda ep: f"{ep.split(':')[0]}:<hidden>"))
pulumi.export('bucket_name', bucket.id)
pulumi.export('bucket_endpoint', pulumi.Output.concat('http://', bucket.website_endpoint))