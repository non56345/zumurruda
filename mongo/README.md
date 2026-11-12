# تجهيز MongoDB يدوياً (في حال تعطيل ZUM_AUTO_INIT)

الموقع يجهّز قاعدة بيانات MongoDB تلقائياً عند أول تشغيل طالما أن `ZUM_AUTO_INIT=1` (الوضع الافتراضي).

إذا رغبت في تعطيل التهيئة التلقائية (`ZUM_AUTO_INIT=0`) وتجهيز القاعدة يدوياً:

## 1. إنشاء الفهارس
باستخدام أداة `mongosh`:
```bash
mongosh "MONGODB_URI" mongo/indexes.js
```

## 2. استيراد البيانات الأولية (وثيقة `site`)
باستخدام `mongoimport`:
```bash
mongoimport --uri="MONGODB_URI" --collection=site --file=mongo/site.seed.json
```
أو من داخل `mongosh`:
```javascript
const fs = require('fs');
const seed = JSON.parse(fs.readFileSync('mongo/site.seed.json', 'utf8'));
db.site.updateOne({ _id: "site" }, { $setOnInsert: seed }, { upsert: true });
db.meta.updateOne({ _id: "init" }, { $set: { schema_version: 1, at: Date.now() / 1000 } }, { upsert: true });
```
