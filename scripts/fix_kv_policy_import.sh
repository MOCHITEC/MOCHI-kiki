#!/usr/bin/env bash
#
# Key Vault access policy が az で先に作成済の場合に terraform に取り込むスクリプト。
# deploy_recall_ws.sh の terraform apply で "already exists" エラーが出たときの修復用。

set -euo pipefail

cd "$(dirname "$0")/.."

SUB_ID="$(az account show --query id -o tsv)"
OID="$(az ad signed-in-user show --query id -o tsv)"
RG_NAME="${RG_NAME:-rg-mochi-kiki}"
KV_NAME="${KV_NAME:-mochikiki-kv-dev}"

POLICY_ID="/subscriptions/${SUB_ID}/resourceGroups/${RG_NAME}/providers/Microsoft.KeyVault/vaults/${KV_NAME}/objectId/${OID}"

echo "Subscription : $SUB_ID"
echo "Object ID    : $OID"
echo "Policy ID    : $POLICY_ID"
echo ""

cd infra

export TF_VAR_subscription_id="$SUB_ID"
export TF_VAR_gpt4o_capacity="${TF_VAR_gpt4o_capacity:-100}"

echo "::: terraform import azurerm_key_vault_access_policy.terraform_operator"
terraform import azurerm_key_vault_access_policy.terraform_operator "$POLICY_ID"

echo ""
echo "::: terraform plan で差分を確認"
terraform plan

echo ""
echo "✅ import 完了。差分が 'No changes' なら次は:"
echo "   cd .. && SKIP_TF=1 ./scripts/deploy_recall_ws.sh"
