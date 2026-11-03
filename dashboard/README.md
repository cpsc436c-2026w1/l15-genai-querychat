# dashboard

The taxi questions app as a web page: querychat over the NYC yellow-taxi table of January 2024 (2,964,624 trips),
with a model selector (Qwen 3.8 27B on Groq, GPT-5.4 nano and GPT-5.4 mini on OpenAI), a password page, a cap of
15 questions per browser session and 2,000 model calls per container (about 3 calls per question). It runs as one
container on AWS Fargate. Adapted from the DSCI 532 groqdemo app and the taxi apps of DSCI 532 lecture 7.

## Data: read from S3 once, then locked

The table is not in the image. At start, before querychat gets the connection, `app.py`:

1. opens a DuckDB database file on the container's local disk (`/tmp/taxi.duckdb`, with a 400 MB memory limit
   and spilling to that disk beyond it).
2. loads the `httpfs` and `aws` extensions, installed in the image at build, so nothing is downloaded at start.
3. creates an S3 secret with `PROVIDER credential_chain`, which finds the task role's credentials.
4. copies `s3://$BUCKET/$KEY` into table `taxi`, then drops the secret.
5. sets `enable_external_access = false`, then `lock_configuration = true`.

After that the model's SQL can query `taxi` but cannot read S3 or any file, and it cannot switch the setting
back. The task role is the only credential the app holds, and it may read one object. The model keys reach the
app as environment variables, injected by ECS from Secrets Manager at task start. The app makes no AWS call
after the S3 read.

## Scripts

All of them source `common.sh`, which holds the settings and checks the account and the region before any call.

| script | what it does | AWS |
|---|---|---|
| `common.sh` | settings with defaults: `REGION`, `ACCOUNT` (from `aws sts get-caller-identity`), `NAME`, `BUCKET`, `KEY`, `SECRET_NAME`, `EXEC_ROLE_NAME`, `TASK_ROLE_NAME`, `IMAGE_TAG` | read |
| `deploy.sh` | ECR repo (keeps the last 3 images), image build (arm64) and push, log group (7 days), cluster, security group (port 8000), task definition (0.5 vCPU, 1 GB, ARM64). Starts nothing. Needs `BUCKET` and `DASH_PASSWORD` | write |
| `start.sh [revision]` | one Fargate task with a public IP, then its URL. Bills until `stop.sh` | write |
| `url.sh` | the running task's URL | read |
| `stop.sh` | stops the task and keeps everything else | write |
| `teardown.sh` | removes everything `deploy.sh` made and lists what is left. Keeps the roles and the secret | write |

```bash
export BUCKET=<your bucket>            # holding $KEY, default genai/taxi_2024-01.parquet (bash data/fetch.sh, then upload)
read -rs DASH_PASSWORD; export DASH_PASSWORD
bash deploy.sh && bash start.sh        # about 2 minutes, prints http://<ip>:8000/
bash stop.sh                           # when you are done (bash teardown.sh removes the rest)
```

What it costs while it runs is on the Cost report page: about $0.027 an hour in ca-central-1, plus the model calls.

## Set up first, by whoever owns the account

| what | allowed to do |
|---|---|
| secret `$SECRET_NAME` | a JSON object with `GROQ_API_KEY` and `OPENAI_API_KEY` |
| execution role `$EXEC_ROLE_NAME`, trusted by `ecs-tasks.amazonaws.com` | pull the image from ECR, write to the log group, read that one secret (`secretsmanager:GetSecretValue`) |
| task role `$TASK_ROLE_NAME`, trusted by `ecs-tasks.amazonaws.com` | `s3:GetObject` on `$BUCKET/$KEY`. Nothing else |
| whoever runs the scripts | ECR, ECS, CloudWatch Logs and security groups in the default VPC, `iam:GetRole` and `iam:PassRole` on the two roles, `secretsmanager:DescribeSecret` on the secret |

The password is a plain environment variable of the task definition: anyone who can describe task definitions in
the account can read it. It is never written to the repo or the image.

## Run locally

```bash
uv sync
TAXI_S3=s3://$BUCKET/$KEY DASH_PASSWORD=test uv run shiny run app.py --port 8000    # your AWS credentials read the file
```

Without the two model keys the password page works and the dashboard says no model key is set. With
`GROQ_API_KEY` or `OPENAI_API_KEY` in the environment the chat works.
