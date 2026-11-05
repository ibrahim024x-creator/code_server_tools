# devtools-bridge

أداة تكتشف أدوات التطوير المثبتة مسبقاً في PATH وتربطها تلقائياً مع VS Code / code-server — دون إعادة تثبيت أي شيء.

## ماذا تفعل

1. **تفحص PATH** وتجد الأدوات التنفيذية المثبتة (LSP, DAP, formatters, linters, compilers).
2. **تحدد اللغة والوظيفة** لكل أداة باستخدام سجل مدمج يغطي 15 لغة.
3. **تولّد أو تعدّل `settings.json`** تلقائياً مع ضبط مسارات الأدوات الفعلية.
4. **تحدد الإضافات المطلوبة** وتثبتها عبر `--install-extensions`.
5. **تتجنب التكرار** — تختار أول أداة موجودة لكل دور.

## اللغات المدعومة (15)

Python, JavaScript/TypeScript, Go, Rust, C/C++, Java, Ruby, PHP, C#, HTML/CSS, Shell/Bash, Lua, Dart, Kotlin, SQL, JSON/YAML/TOML.

## الاستخدام

```bash
# فحص وعرض ما تم اكتشافه فقط (دون كتابة)
python3 devtools-bridge.py --dry-run

# اكتشاف + كتابة settings.json
python3 devtools-bridge.py

# اكتشاف + كتابة settings.json + تثبيت الإضافات
python3 devtools-bridge.py --install-extensions

# تحديد مسار settings.json يدوياً
python3 devtools-bridge.py --settings ~/.local/share/code-server/User/settings.json

# تقييد بلغات معينة
python3 devtools-bridge.py --languages python,go,rust

# حفظ تقرير JSON
python3 devtools-bridge.py --report report.json
```

## الخيارات

| الخيار | الوصف |
|---|---|
| `--dry-run` | عرض التغييرات دون كتابة أو تثبيت |
| `--settings PATH` | مسار settings.json (افتراضي: كشف تلقائي) |
| `--registry PATH` | مسار registry.json (افتراضي: بجانب السكربت) |
| `--install-extensions` | تثبيت الإضافات الناقصة |
| `--report PATH` | حفظ تقرير JSON |
| `--no-merge` | استبدال settings.json بدلاً من الدمج |
| `--languages a,b,c` | تقييد بلغات معينة |

## إضافة أدوات بنفسك

عدّل `registry.json` — أضف اسم الأداة التنفيذية تحت اللغة والدور المناسبين. كل أداة تحتاج:

```json
{
  "executables": ["اسم-الأداة"],
  "vscodeExtension": "معرف-الإضافة",
  "settings": {
    "مفتاح-الإعداد": "القيمة"
  }
}
```

العنصر النائب `{path}` يُستبدل بالمسار الفعلي للأداة المكتشفة.

## القيود

- Tree-sitter parsers في VS Code/code-server تكون مدمجة في الإضافات وليست أدوات مستقلة على PATH.
- الإضافات تُثبت من Open VSX (code-server) أو Marketplace (VS Code) حسب الـ CLI المتاح.
- الأداة تختار أول أداة موجودة لكل دور حسب ترتيبها في registry.json — رتّب الأدوات المفضلة أولاً.
