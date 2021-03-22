#!/usr/bin/env bash

set -e
set -o pipefail

if [[ "$1" == "" ]];
then
  echo "Please provide config file as command line parameter"
  exit 1
fi

# read configuration file
source "$1"

echo -e "\n########### Creating project $project_name ###########\n"
gcloud projects create "$project_name" --set-as-default

# take first billing account from the top
billing_account=$(gcloud beta billing accounts list | awk 'NR==2{print $1}')
echo -e "\n########### Linking billing account ID $billing_account to project $project_name ###########\n"
gcloud beta billing projects link "$project_name" --billing-account "$billing_account"

echo -e "\n########### Creating service account $service_account ###########\n"
gcloud iam service-accounts create "$service_account"

echo -e "\n########### Enabling secretmanager, cloud functions, cloud build and cloudscheduler apis ###########\n"
gcloud services enable secretmanager.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com

echo -e "\n########### Creating secret $secret_name ###########\n"
echo -n "$slack_token" | gcloud secrets create "$secret_name" --data-file=- --replication-policy=automatic

echo -e "\n########### Adding permissions to read secret ###########\n"
gcloud projects add-iam-policy-binding "$project_name" --role=roles/secretmanager.secretAccessor \
                                       --member=serviceAccount:"$service_account@$project_name.iam.gserviceaccount.com"

# using python37 runtime as newer ones do not provide GCP_PROJECT env var
echo -e "\n########### Deploying function $function_name ###########\n"
deployment_output=$(gcloud functions deploy "$function_name" --region="$function_region" --allow-unauthenticated \
                                           --runtime=python37 --trigger-http --entry-point=main --memory=256MB \
                                           --timeout=300s --set-env-vars=SLACK_TOKEN_SECRET="$secret_name" \
                                           --source="$function_source_path" \
                                           --service-account="$service_account@$project_name.iam.gserviceaccount.com")
echo -e "\n$deployment_output\n"

echo -e "\n########### Calling function $function_name for 5 days as as smoke test ###########\n"
gcloud functions call "$function_name" --data='{"days": "5"}'

echo -e "\n########### Creating cloud scheduler job (which requires App creation) ###########\n"
function_uri=$(echo "$deployment_output" | grep 'url:' | awk '{print $2}')
function_uri="$function_uri""?days=$days&just_a_test=0"
tzname=$(find /usr/share/zoneinfo/ -type f | xargs md5sum | grep $(md5sum /etc/localtime  | cut -d' ' -f1) | awk '{print $2}')
# cloud scheduler requires to create an app in App Engine, and it's region naming convention may slightly differ
gcloud app create --region="$app_region"
gcloud scheduler jobs create http "$job_name" --schedule="$job_schedule" --uri="$function_uri" \
                                  --http-method=GET --time-zone="${tzname#/usr/share/zoneinfo/}"

echo -e "\n########### All done. ###########"
