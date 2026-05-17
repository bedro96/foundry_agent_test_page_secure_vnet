#!/bin/bash

# 고유 태그 생성 — ACA 이미지 캐시 문제를 방지합니다
TAG="v$(date +%Y%m%d-%H%M%S)"
echo "🏷️  이미지 태그: $TAG"

# ACR에 이미지 빌드 및 푸시
az acr build --registry iotacr --image lgit-chat-frontend:$TAG .

# 컨테이너 앱을 새 이미지로 업데이트
az containerapp update --name lgit-chat-frontend --resource-group aks-rg --image iotacr.azurecr.io/lgit-chat-frontend:$TAG
