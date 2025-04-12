"""An AWS Python Pulumi program"""

import pulumi
from pulumi_aws import s3
import pulumi_aws as aws


# Configuration
config = pulumi.Config()
env = config.require("environment")

# Prefix for 'prod' or 'dev' environment
STACK_PREFIX = "" if env == 'prod' else f"{env}-"

# Resources
# Create an AWS resource (S3 Bucket)
bucket = s3.Bucket(
    f"{STACK_PREFIX}my-bucket",
    # bucket=f"{STACK_PREFIX}my-bucket",
    website={
        "index_document": "index.html",
    }
)

ownership_controls = s3.BucketOwnershipControls(
    'ownership-controls',
    bucket=bucket.id,
    rule={
        "object_ownership": 'ObjectWriter',
    },
)

public_access_block = s3.BucketPublicAccessBlock(
    'public-access-block', bucket=bucket.id, block_public_acls=False
)

bucket_object = s3.BucketObject(
    'index.html',
    bucket=bucket.id,
    source=pulumi.FileAsset('index.html'),
    content_type='text/html',
    acl='public-read',
    opts=pulumi.ResourceOptions(depends_on=[public_access_block, ownership_controls]),
)

# Export the name of the bucket
pulumi.export('bucket_name', bucket.id)
pulumi.export('bucket_endpoint', pulumi.Output.concat('http://', bucket.website_endpoint))
