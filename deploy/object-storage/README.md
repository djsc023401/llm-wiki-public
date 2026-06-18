# 오브젝트 스토리지 준비

`llm-wiki`는 첨부파일과 원본 파일을 S3 호환 object storage에 저장할 수 있다.

## 준비

```bash
cp deploy/object-storage/.env.example /home/YOUR_USER/services/object-storage/.env
chmod 600 /home/YOUR_USER/services/object-storage/.env
```

필수 값:

- `S3_ENDPOINT`
- `S3_BUCKET`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_REGION`

`S3_BUCKET_NAME`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`는 legacy alias로만 유지한다.

## 버킷 생성

```bash
cd /home/YOUR_USER/projects/llm-wiki
. /home/YOUR_USER/services/object-storage/.env
python scripts/object_storage/create_bucket.py
```

실제 credential은 Git에 커밋하지 않는다.
