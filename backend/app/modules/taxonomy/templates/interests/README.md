# Taxonomy interest templates

Файлы в этой папке описывают интересы, из которых собирается базовое дерево категорий при первом входе пользователя через `POST /taxonomy/initialize/interests`.

## Как добавить новый интерес

1. Создать новый файл `<slug>.json`, например `finance.json`.
2. Добавьть slug в `INTEREST_SPEC_SLUGS` в `backend/app/modules/taxonomy/service.py`.
3. Заполнить верхний уровень:
   - `slug` - стабильный id интереса, совпадает с именем файла;
   - `aliases` - старые или альтернативные slugs, можно `[]`;
   - `name` - название для UI;
   - `description` - краткое описание интереса для выбора в onboarding;
   - `tree` - список root-нод, обычно одна root-нода.
4. Для каждой root и child-ноды указать:
   - `name`;
   - `description`;
   - `profile.summary`;
   - `profile.keywords`;
   - `profile.positive_examples`;
   - `profile.negative_examples`;
   - `children`.

## Минимальный пример

```json
{
  "slug": "finance",
  "aliases": [],
  "name": "Finance",
  "description": "Личные финансы, бюджет, инвестиции и финансовые цели.",
  "tree": [
    {
      "name": "Finance",
      "description": "Финансовые материалы, решения, цели, бюджет и учет денег.",
      "profile": {
        "summary": "Материалы, где финансы являются основной темой: бюджет, расходы, накопления, инвестиции, финансовые цели и решения.",
        "keywords": ["finance", "budget", "expenses", "investments", "savings"],
        "positive_examples": ["План бюджета на месяц.", "Заметка об инвестиционной идее.", "Список регулярных расходов."],
        "negative_examples": ["Бизнес-продажи без личных финансов.", "Личная задача без финансового содержания.", "Статья про продукт без финансового вывода."]
      },
      "children": [
        {
          "name": "Budget",
          "description": "Бюджет, расходы, лимиты, категории трат и планирование денег.",
          "profile": {
            "summary": "Материалы про бюджетирование: расходы, лимиты, категории трат, финансовое планирование и контроль регулярных платежей.",
            "keywords": ["budget", "expenses", "limits", "payments", "planning"],
            "positive_examples": ["Категории расходов на месяц.", "План сократить подписки.", "Заметка о лимитах на покупки."],
            "negative_examples": ["Инвестиционная идея без бюджета.", "Рабочая задача без финансов.", "Общая личная заметка."]
          },
          "children": []
        }
      ]
    }
  ]
}
```

После добавления файла запустить тесты:

```bash
uv run pytest tests/test_taxonomy.py -q
uv run ruff check app/modules/taxonomy tests/test_taxonomy.py
```
