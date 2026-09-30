# JOB Workload Structured Analysis Report

**Database:** `job_imdb`
**Benchmark location:** `.\benchmarks\job`
**Total families:** 33 | **Total query variants:** 113
**Source of truth:** Actual SQL files in `benchmarks/job/*.sql`

---

## Section 1 — Compact Summary Table

| Family | Variants | Tables | JOINs | WHERE | GROUP BY | ORDER BY | Aggregates | Complexity |
|--------|----------|--------|-------|-------|----------|----------|------------|------------|
| 1 | 4 (1a–1d) | 5: company_type, info_type, movie_companies, movie_info_idx, title | Yes | Yes | No | No | MIN | Medium |
| 2 | 4 (2a–2d) | 5: company_name, keyword, movie_companies, movie_keyword, title | Yes | Yes | No | No | MIN | Medium |
| 3 | 3 (3a–3c) | 4: keyword, movie_info, movie_keyword, title | Yes | Yes | No | No | MIN | Medium |
| 4 | 3 (4a–4c) | 5: info_type, keyword, movie_info_idx, movie_keyword, title | Yes | Yes | No | No | MIN | Medium |
| 5 | 3 (5a–5c) | 5: company_type, info_type, movie_companies, movie_info, title | Yes | Yes | No | No | MIN | Medium |
| 6 | 6 (6a–6f) | 5: cast_info, keyword, movie_keyword, name, title | Yes | Yes | No | No | MIN | Medium |
| 7 | 3 (7a–7c) | 8: aka_name, cast_info, info_type, link_type, movie_link, name, person_info, title | Yes | Yes | No | No | MIN | High |
| 8 | 4 (8a–8d) | 7: aka_name, cast_info, company_name, movie_companies, name, role_type, title | Yes | Yes | No | No | MIN | High |
| 9 | 4 (9a–9d) | 8: aka_name, char_name, cast_info, company_name, movie_companies, name, role_type, title | Yes | Yes | No | No | MIN | High |
| 10 | 3 (10a–10c) | 7: char_name, cast_info, company_name, company_type, movie_companies, role_type, title | Yes | Yes | No | No | MIN | High |
| 11 | 4 (11a–11d) | 8: company_name, company_type, keyword, link_type, movie_companies, movie_keyword, movie_link, title | Yes | Yes | No | No | MIN | High |
| 12 | 3 (12a–12c) | 8 instances (7 unique): company_name, company_type, info_type ×2, movie_companies, movie_info, movie_info_idx, title | Yes | Yes | No | No | MIN | High |
| 13 | 4 (13a–13d) | 9 instances (8 unique): company_name, company_type, info_type ×2, kind_type, movie_companies, movie_info, movie_info_idx, title | Yes | Yes | No | No | MIN | High |
| 14 | 3 (14a–14c) | 8 instances (7 unique): info_type ×2, keyword, kind_type, movie_info, movie_info_idx, movie_keyword, title | Yes | Yes | No | No | MIN | High |
| 15 | 4 (15a–15d) | 9: aka_title, company_name, company_type, info_type, keyword, movie_companies, movie_info, movie_keyword, title | Yes | Yes | No | No | MIN | High |
| 16 | 4 (16a–16d) | 8: aka_name, cast_info, company_name, keyword, movie_companies, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 17 | 6 (17a–17f) | 7: cast_info, company_name, keyword, movie_companies, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 18 | 3 (18a–18c) | 7 instances (6 unique): cast_info, info_type ×2, movie_info, movie_info_idx, name, title | Yes | Yes | No | No | MIN | High |
| 19 | 4 (19a–19d) | 10: aka_name, char_name, cast_info, company_name, info_type, movie_companies, movie_info, name, role_type, title | Yes | Yes | No | No | MIN | High |
| 20 | 3 (20a–20c) | 10 instances (9 unique): complete_cast, comp_cast_type ×2, char_name, cast_info, keyword, kind_type, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 21 | 3 (21a–21c) | 9: company_name, company_type, keyword, link_type, movie_companies, movie_info, movie_keyword, movie_link, title | Yes | Yes | No | No | MIN | High |
| 22 | 4 (22a–22d) | 11 instances (10 unique): company_name, company_type, info_type ×2, keyword, kind_type, movie_companies, movie_info, movie_info_idx, movie_keyword, title | Yes | Yes | No | No | MIN | High |
| 23 | 3 (23a–23c) | 11: complete_cast, comp_cast_type, company_name, company_type, info_type, keyword, kind_type, movie_companies, movie_info, movie_keyword, title | Yes | Yes | No | No | MIN | High |
| 24 | 2 (24a–24b) | 12: aka_name, char_name, cast_info, company_name, info_type, keyword, movie_companies, movie_info, movie_keyword, name, role_type, title | Yes | Yes | No | No | MIN | High |
| 25 | 3 (25a–25c) | 9 instances (8 unique): cast_info, info_type ×2, keyword, movie_info, movie_info_idx, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 26 | 3 (26a–26c) | 12 instances (11 unique): complete_cast, comp_cast_type ×2, char_name, cast_info, info_type, keyword, kind_type, movie_info_idx, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 27 | 3 (27a–27c) | 12 instances (11 unique): complete_cast, comp_cast_type ×2, company_name, company_type, keyword, link_type, movie_companies, movie_info, movie_keyword, movie_link, title | Yes | Yes | No | No | MIN | High |
| 28 | 3 (28a–28c) | 14 instances (12 unique): complete_cast, comp_cast_type ×2, company_name, company_type, info_type ×2, keyword, kind_type, movie_companies, movie_info, movie_info_idx, movie_keyword, title | Yes | Yes | No | No | MIN | High |
| 29 | 3 (29a–29c) | 17 instances (15 unique): aka_name, complete_cast, comp_cast_type ×2, char_name, cast_info, company_name, info_type ×2, keyword, movie_companies, movie_info, movie_keyword, name, person_info, role_type, title | Yes | Yes | No | No | MIN | High |
| 30 | 3 (30a–30c) | 12 instances (10 unique): complete_cast, comp_cast_type ×2, cast_info, info_type ×2, keyword, movie_info, movie_info_idx, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 31 | 3 (31a–31c) | 11 instances (10 unique): cast_info, company_name, info_type ×2, keyword, movie_companies, movie_info, movie_info_idx, movie_keyword, name, title | Yes | Yes | No | No | MIN | High |
| 32 | 2 (32a–32b) | 6 instances (5 unique): keyword, link_type, movie_keyword, movie_link, title ×2 | Yes | Yes | No | No | MIN | Medium |
| 33 | 3 (33a–33c) | 14 instances (8 unique): company_name ×2, info_type ×2, kind_type ×2, link_type, movie_companies ×2, movie_info_idx ×2, movie_link, title ×2 | Yes | Yes | No | No | MIN | High |

---

## Section 2 — Detailed Family-Level Observations

### Family 1
- **Variants:** 4 — [1a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/1a.sql), [1b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/1b.sql), [1c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/1c.sql), [1d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/1d.sql)
- **Tables:** company_type, info_type, movie_companies, movie_info_idx, title (5)
- **Main JOIN columns:** `ct.id = mc.company_type_id`, `t.id = mc.movie_id`, `t.id = mi_idx.movie_id`, `mc.movie_id = mi_idx.movie_id`, `it.id = mi_idx.info_type_id`
- **WHERE predicates:** `ct.kind = 'production companies'`; `it.info = 'top 250 rank'/'bottom 10 rank'`; `mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'`; various `mc.note LIKE` patterns; `t.production_year > X` or `BETWEEN`
- **WHERE columns:** company_type.kind, info_type.info, movie_companies.note, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mc.note), MIN(t.title), MIN(t.production_year)
- **Potential indexable columns:** company_type(id, kind), info_type(id, info), movie_companies(company_type_id, movie_id, note), movie_info_idx(movie_id, info_type_id), title(id, production_year)
- **Structurally similar:** Yes — identical tables/joins, varying only filter constants
- **Unusual:** Redundant join cycle on movie_id; substring LIKE with leading wildcards on mc.note

### Family 2
- **Variants:** 4 — [2a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/2a.sql), [2b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/2b.sql), [2c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/2c.sql), [2d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/2d.sql)
- **Tables:** company_name, keyword, movie_companies, movie_keyword, title (5)
- **Main JOIN columns:** `cn.id = mc.company_id`, `mc.movie_id = t.id`, `t.id = mk.movie_id`, `mc.movie_id = mk.movie_id`, `mk.keyword_id = k.id`
- **WHERE predicates:** `cn.country_code = '[de]'/'[nl]'/'[sm]'/'[us]'`; `k.keyword = 'character-name-in-title'`
- **WHERE columns:** company_name.country_code, keyword.keyword
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(t.title)
- **Potential indexable columns:** company_name(id, country_code), keyword(id, keyword), movie_companies(company_id, movie_id), movie_keyword(movie_id, keyword_id), title(id)
- **Structurally similar:** Yes — differs solely by country_code literal
- **Unusual:** Redundant join cycle on movie_id; uniform template across all variants

### Family 3
- **Variants:** 3 — [3a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/3a.sql), [3b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/3b.sql), [3c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/3c.sql)
- **Tables:** keyword, movie_info, movie_keyword, title (4)
- **Main JOIN columns:** `t.id = mi.movie_id`, `t.id = mk.movie_id`, `mk.movie_id = mi.movie_id`, `k.id = mk.keyword_id`
- **WHERE predicates:** `k.keyword LIKE '%sequel%'`; `mi.info IN (...)` (country/language lists); `t.production_year > X`
- **WHERE columns:** keyword.keyword, movie_info.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(t.title)
- **Potential indexable columns:** keyword(id, keyword), movie_info(movie_id, info), movie_keyword(movie_id, keyword_id), title(id, production_year)
- **Structurally similar:** Yes — same structure, varying filter values
- **Unusual:** Benchmark typo 'Denish' instead of 'Danish'; leading wildcard LIKE on keyword

### Family 4
- **Variants:** 3 — [4a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/4a.sql), [4b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/4b.sql), [4c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/4c.sql)
- **Tables:** info_type, keyword, movie_info_idx, movie_keyword, title (5)
- **Main JOIN columns:** `t.id = mi_idx.movie_id`, `t.id = mk.movie_id`, `mk.movie_id = mi_idx.movie_id`, `k.id = mk.keyword_id`, `it.id = mi_idx.info_type_id`
- **WHERE predicates:** `it.info = 'rating'`; `k.keyword LIKE '%sequel%'`; `mi_idx.info > 'X.X'` (string inequality); `t.production_year > X`
- **WHERE columns:** info_type.info, keyword.keyword, movie_info_idx.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi_idx.info), MIN(t.title)
- **Potential indexable columns:** info_type(id, info), keyword(id, keyword), movie_info_idx(movie_id, info_type_id, info), movie_keyword(movie_id, keyword_id), title(id, production_year)
- **Structurally similar:** Yes
- **Unusual:** Lexicographic string inequality on numeric rating stored as text

### Family 5
- **Variants:** 3 — [5a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/5a.sql), [5b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/5b.sql), [5c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/5c.sql)
- **Tables:** company_type, info_type, movie_companies, movie_info, title (5)
- **Main JOIN columns:** `t.id = mi.movie_id`, `t.id = mc.movie_id`, `mc.movie_id = mi.movie_id`, `ct.id = mc.company_type_id`, `it.id = mi.info_type_id`
- **WHERE predicates:** `ct.kind = 'production companies'`; `mc.note LIKE/NOT LIKE` patterns; `mi.info IN (...)` country lists; `t.production_year > X`
- **WHERE columns:** company_type.kind, movie_companies.note, movie_info.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(t.title)
- **Potential indexable columns:** company_type(id, kind), info_type(id), movie_companies(company_type_id, movie_id, note), movie_info(movie_id, info_type_id, info), title(id, production_year)
- **Structurally similar:** Yes
- **Unusual:** info_type joined but unconstrained in WHERE and unprojected; benchmark typo 'Denish'

### Family 6
- **Variants:** 6 — [6a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/6a.sql), [6b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/6b.sql), [6c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/6c.sql), [6d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/6d.sql), [6e.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/6e.sql), [6f.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/6f.sql)
- **Tables:** cast_info, keyword, movie_keyword, name, title (5)
- **Main JOIN columns:** `k.id = mk.keyword_id`, `t.id = mk.movie_id`, `t.id = ci.movie_id`, `ci.movie_id = mk.movie_id`, `n.id = ci.person_id`
- **WHERE predicates:** `k.keyword = 'marvel-cinematic-universe'` or `IN(...)` keyword lists; `n.name LIKE '%Downey%Robert%'` (6a–6e, absent in 6f); `t.production_year > X`
- **WHERE columns:** keyword.keyword, name.name, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(k.keyword), MIN(n.name), MIN(t.title)
- **Potential indexable columns:** cast_info(movie_id, person_id), keyword(id, keyword), movie_keyword(keyword_id, movie_id), name(id, name), title(id, production_year)
- **Structurally similar:** Partially — 6f omits the name.name predicate
- **Unusual:** 6f joins name but has no filter on it; joins two large fact tables (cast_info, movie_keyword) on movie_id

### Family 7
- **Variants:** 3 — [7a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/7a.sql), [7b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/7b.sql), [7c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/7c.sql)
- **Tables:** aka_name, cast_info, info_type, link_type, movie_link, name, person_info, title (8)
- **Main JOIN columns:** `n.id = an.person_id`, `n.id = pi.person_id`, `ci.person_id = n.id`, `t.id = ci.movie_id`, `ml.linked_movie_id = t.id`, `lt.id = ml.link_type_id`, `it.id = pi.info_type_id` + redundant person_id and movie_id cycles
- **WHERE predicates:** `an.name LIKE '%a%'`; `it.info = 'mini biography'`; `lt.link = 'features'` or `IN(...)`; `n.name_pcode_cf BETWEEN/LIKE`; `n.gender` conditions; `pi.note` filters; `t.production_year BETWEEN`
- **WHERE columns:** aka_name.name, info_type.info, link_type.link, name.name_pcode_cf, name.gender, name.name, person_info.note, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(n.name), MIN(t.title) [7a,7b]; MIN(n.name), MIN(pi.info) [7c]
- **Potential indexable columns:** aka_name(person_id, name), cast_info(person_id, movie_id), info_type(id, info), link_type(id, link), movie_link(linked_movie_id, link_type_id), name(id, name_pcode_cf, gender, name), person_info(person_id, info_type_id, note), title(id, production_year)
- **Structurally similar:** Yes — identical tables/joins, filter values differ
- **Unusual:** Joins movie_link on `linked_movie_id` not `movie_id`; 4-clique on person_id; disjunctive gender/name conditions

### Family 8
- **Variants:** 4 — [8a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/8a.sql), [8b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/8b.sql), [8c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/8c.sql), [8d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/8d.sql)
- **Tables:** aka_name, cast_info, company_name, movie_companies, name, role_type, title (7)
- **Main JOIN columns:** `an.person_id = n.id`, `n.id = ci.person_id`, `ci.movie_id = t.id`, `t.id = mc.movie_id`, `mc.company_id = cn.id`, `ci.role_id = rt.id` + redundant cycles
- **WHERE predicates:** 8a/8b: `ci.note = '(voice: English version)'`, `cn.country_code = '[jp]'`, `mc.note LIKE/NOT LIKE`, `n.name LIKE/NOT LIKE`, `rt.role = 'actress'`, year/title filters in 8b; 8c/8d: `cn.country_code = '[us]'`, `rt.role = 'writer'/'costume designer'` only
- **WHERE columns:** cast_info.note, company_name.country_code, movie_companies.note, name.name, role_type.role, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(an.name), MIN(t.title)
- **Potential indexable columns:** aka_name(person_id), name(id, name), cast_info(person_id, movie_id, role_id, note), title(id, production_year, title), movie_companies(movie_id, company_id, note), company_name(id, country_code), role_type(id, role)
- **Structurally similar:** Yes — but dramatic selectivity variation (8a/8b heavily filtered, 8c/8d lightly filtered)
- **Unusual:** 8c/8d leave 5 tables unconstrained by WHERE; alias typo in 8b

### Family 9
- **Variants:** 4 — [9a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/9a.sql), [9b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/9b.sql), [9c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/9c.sql), [9d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/9d.sql)
- **Tables:** aka_name, char_name, cast_info, company_name, movie_companies, name, role_type, title (8)
- **Main JOIN columns:** `ci.movie_id = t.id`, `t.id = mc.movie_id`, `ci.movie_id = mc.movie_id`, `mc.company_id = cn.id`, `ci.role_id = rt.id`, `n.id = ci.person_id`, `chn.id = ci.person_role_id`, `an.person_id = n.id`, `an.person_id = ci.person_id`
- **WHERE predicates:** ci.note IN lists; `cn.country_code = '[us]'`; mc.note LIKE patterns (9a, 9b); `n.gender = 'f'`; `n.name LIKE '%Ang%'/'%Angel%'/'%An%'` (9a/9b/9c); `rt.role = 'actress'`; `t.production_year BETWEEN` (9a, 9b)
- **WHERE columns:** cast_info.note, company_name.country_code, movie_companies.note, name.gender, name.name, role_type.role, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(an.name), MIN(chn.name), MIN(t.title) [9a]; +MIN(n.name) [9b-9d]
- **Structurally similar:** Yes — progressive predicate relaxation across variants
- **Unusual:** Variants progressively remove filters from 9a→9d; redundant join cycles

### Family 10
- **Variants:** 3 — [10a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/10a.sql), [10b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/10b.sql), [10c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/10c.sql)
- **Tables:** char_name, cast_info, company_name, company_type, movie_companies, role_type, title (7)
- **Main JOIN columns:** `t.id = mc.movie_id`, `t.id = ci.movie_id`, `ci.movie_id = mc.movie_id`, `chn.id = ci.person_role_id`, `rt.id = ci.role_id`, `cn.id = mc.company_id`, `ct.id = mc.company_type_id`
- **WHERE predicates:** `ci.note LIKE` patterns; `cn.country_code = '[ru]'/'[us]'`; `rt.role = 'actor'` (10a, 10b); `t.production_year > X`
- **WHERE columns:** cast_info.note, company_name.country_code, role_type.role, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(chn.name), MIN(t.title)
- **Structurally similar:** Yes — 10c omits role_type filter
- **Unusual:** company_type joined but never filtered or projected; in 10c role_type also unfiltered/unprojected

### Family 11
- **Variants:** 4 — [11a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/11a.sql), [11b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/11b.sql), [11c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/11c.sql), [11d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/11d.sql)
- **Tables:** company_name, company_type, keyword, link_type, movie_companies, movie_keyword, movie_link, title (8)
- **Main JOIN columns:** `lt.id = ml.link_type_id`, `ml.movie_id = t.id`, `t.id = mk.movie_id`, `mk.keyword_id = k.id`, `t.id = mc.movie_id`, `mc.company_type_id = ct.id`, `mc.company_id = cn.id` + redundant movie_id clique
- **WHERE predicates:** `cn.country_code != '[pl]'`; `cn.name LIKE '%Film%'/'%Warner%'`; `ct.kind = 'production companies'` (11a/b) or `!= 'production companies'` (11c/d); `k.keyword = 'sequel'` or IN list; `lt.link LIKE '%follow%'` (11a/b); `mc.note IS NULL` (11a/b) / `IS NOT NULL` (11c/d); `t.production_year BETWEEN/>/=`; `t.title LIKE '%Money%'` (11b)
- **WHERE columns:** company_name.country_code, company_name.name, company_type.kind, keyword.keyword, link_type.link, movie_companies.note, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn.name), MIN(lt.link/mc.note), MIN(t.title)
- **Structurally similar:** Yes — but 11a/b vs 11c/d invert several predicates
- **Unusual:** Negative predicates (`!=`, `NOT LIKE`, `IS NULL` / `IS NOT NULL`); 11c/d leave link_type unfiltered; 4-clique on movie_id

### Family 12
- **Variants:** 3 — [12a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/12a.sql), [12b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/12b.sql), [12c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/12c.sql)
- **Tables:** 8 instances (7 unique): company_name, company_type, info_type ×2, movie_companies, movie_info, movie_info_idx, title
- **Main JOIN columns:** `t.id = mi.movie_id`, `t.id = mi_idx.movie_id`, `mi.info_type_id = it1.id`, `mi_idx.info_type_id = it2.id`, `t.id = mc.movie_id`, `ct.id = mc.company_type_id`, `cn.id = mc.company_id` + redundant movie_id clique
- **WHERE predicates:** `cn.country_code = '[us]'`; `ct.kind` conditions; `it1.info = 'genres'/'budget'`; `it2.info = 'rating'/'bottom 10 rank'`; `mi.info IN(...)` genre lists; `mi_idx.info > 'X.X'`; `t.production_year` ranges; `t.title LIKE 'Birdemic%'/'%Movie%'` (12b)
- **WHERE columns:** company_name.country_code, company_type.kind, info_type.info, movie_info.info, movie_info_idx.info, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn.name), MIN(mi_idx.info), MIN(t.title) [12a, 12c]; MIN(mi.info), MIN(t.title) [12b]
- **Structurally similar:** Yes
- **Unusual:** info_type self-joined (2 instances); 12b leaves mi_idx.info unfiltered and unprojected; lexicographic string comparison on ratings; alias typo `unsuccsessful_movie`

### Family 13
- **Variants:** 4 — [13a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/13a.sql), [13b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/13b.sql), [13c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/13c.sql), [13d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/13d.sql)
- **Tables:** 9 instances (8 unique): company_name, company_type, info_type ×2, kind_type, movie_companies, movie_info, movie_info_idx, title
- **Main JOIN columns:** `t.id = mi/mc/miidx.movie_id`, `kt.id = t.kind_id`, `cn.id = mc.company_id`, `ct.id = mc.company_type_id`, `it2.id = mi.info_type_id`, `it.id = miidx.info_type_id` + 4-way movie_id clique
- **WHERE predicates:** `ct.kind = 'production companies'`; `it.info = 'rating'`; `it2.info = 'release dates'`; `kt.kind = 'movie'`; `cn.country_code = '[de]'/'[us]'`; title LIKE patterns (13b/13c)
- **WHERE columns:** company_name.country_code, company_type.kind, info_type.info, kind_type.kind, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN (varies: mi.info or cn.name, plus miidx.info and t.title)
- **Structurally similar:** Yes
- **Unusual:** info_type self-joined; redundant 4-table movie_id clique; 13b uses `LIKE '%..%'` vs 13c uses `LIKE '..%'` (trailing vs leading wildcard)

### Family 14
- **Variants:** 3 — [14a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/14a.sql), [14b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/14b.sql), [14c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/14c.sql)
- **Tables:** 8 instances (7 unique): info_type ×2, keyword, kind_type, movie_info, movie_info_idx, movie_keyword, title
- **Main JOIN columns:** `kt.id = t.kind_id`, `t.id = mi/mk/mi_idx.movie_id`, `k.id = mk.keyword_id`, `it1.id = mi.info_type_id`, `it2.id = mi_idx.info_type_id` + transitive clique
- **WHERE predicates:** `it1.info = 'countries'`; `it2.info = 'rating'`; `k.keyword IN(...)` murder-related keywords; `kt.kind = 'movie'`/IN list; `mi.info IN(...)` countries; `mi_idx.info < '8.5'` or `> '6.0'`; `t.production_year > X`; title LIKE patterns (14b)
- **WHERE columns:** info_type.info, keyword.keyword, kind_type.kind, movie_info.info, movie_info_idx.info, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi_idx.info), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** Redundant `k.keyword IS NOT NULL` in 14c; typo 'Denish' in 14a/14b vs 'Danish' in 14c; string inequality on rating

### Family 15
- **Variants:** 4 — [15a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/15a.sql), [15b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/15b.sql), [15c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/15c.sql), [15d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/15d.sql)
- **Tables:** aka_title, company_name, company_type, info_type, keyword, movie_companies, movie_info, movie_keyword, title (9)
- **Main JOIN columns:** `t.id = at/mi/mk/mc.movie_id` + complete 5-table clique (all 10 pairwise combinations) on movie_id; `k.id = mk.keyword_id`, `it1.id = mi.info_type_id`, `cn.id = mc.company_id`, `ct.id = mc.company_type_id`
- **WHERE predicates:** `cn.country_code = '[us]'`; `cn.name = 'YouTube'` (15b); `it1.info = 'release dates'`; `mi.note LIKE '%internet%'`; `mi.info LIKE 'USA:% 200%'` patterns; `mc.note LIKE` patterns (15a/b); `t.production_year > X` / `BETWEEN`
- **WHERE columns:** company_name.country_code, company_name.name, info_type.info, movie_companies.note, movie_info.note, movie_info.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi.info/at.title), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** Complete 5-table clique on movie_id (10 join conditions); keyword table joined but never filtered in any variant; multiple wildcard LIKE patterns

### Family 16
- **Variants:** 4 — [16a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/16a.sql), [16b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/16b.sql), [16c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/16c.sql), [16d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/16d.sql)
- **Tables:** aka_name, cast_info, company_name, keyword, movie_companies, movie_keyword, name, title (8)
- **Main JOIN columns:** `an.person_id = n.id`, `n.id = ci.person_id`, `an.person_id = ci.person_id`, `ci.movie_id = t.id`, `t.id = mk/mc.movie_id`, `ci.movie_id = mc/mk.movie_id`, `mc.movie_id = mk.movie_id`, `mk.keyword_id = k.id`, `mc.company_id = cn.id`
- **WHERE predicates:** `cn.country_code = '[us]'`; `k.keyword = 'character-name-in-title'`; `t.episode_nr` range filters (varying by variant; absent in 16b)
- **WHERE columns:** company_name.country_code, keyword.keyword, title.episode_nr
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(an.name), MIN(t.title)
- **Structurally similar:** Yes — only differs in episode_nr range
- **Unusual:** Dual redundant join cliques (3-way on person_id, 4-way on movie_id); filters on TV series attribute `t.episode_nr`

### Family 17
- **Variants:** 6 — [17a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/17a.sql), [17b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/17b.sql), [17c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/17c.sql), [17d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/17d.sql), [17e.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/17e.sql), [17f.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/17f.sql)
- **Tables:** cast_info, company_name, keyword, movie_companies, movie_keyword, name, title (7)
- **Main JOIN columns:** `n.id = ci.person_id`, `ci.movie_id = t.id`, `t.id = mk/mc.movie_id`, `ci.movie_id = mc/mk.movie_id`, `mc.movie_id = mk.movie_id`, `mk.keyword_id = k.id`, `mc.company_id = cn.id`
- **WHERE predicates:** `k.keyword = 'character-name-in-title'`; `cn.country_code = '[us]'` (17a, 17e only); `n.name LIKE 'B%'/'Z%'/'X%'/'%Bert%'/'%B%'` (varying by variant)
- **WHERE columns:** keyword.keyword, company_name.country_code, name.name
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(n.name)
- **Structurally similar:** Yes — varying name patterns and country_code presence
- **Unusual:** 17a/b/c project MIN(n.name) twice under two aliases; in 17b/c/d/f company_name is joined but unfiltered; 4-way movie_id clique

### Family 18
- **Variants:** 3 — [18a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/18a.sql), [18b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/18b.sql), [18c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/18c.sql)
- **Tables:** 7 instances (6 unique): cast_info, info_type ×2, movie_info, movie_info_idx, name, title
- **Main JOIN columns:** `t.id = mi/mi_idx/ci.movie_id`, `n.id = ci.person_id`, `it1.id = mi.info_type_id`, `it2.id = mi_idx.info_type_id` + 4-way movie_id clique
- **WHERE predicates:** `ci.note IN(...)` (producer vs writer roles); `it1.info = 'budget'/'genres'`; `it2.info = 'votes'/'rating'`; `mi.info IN(...)` (18b/c); `mi_idx.info > '8.0'` (18b); `n.gender = 'm'/'f'`; `n.name LIKE '%Tim%'` (18a); `t.production_year BETWEEN` (18b)
- **WHERE columns:** cast_info.note, info_type.info, movie_info.info, movie_info.note, movie_info_idx.info, name.gender, name.name, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi.info), MIN(mi_idx.info), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** info_type self-joined; redundant `n.gender IS NOT NULL` alongside `= 'f'` in 18b; string inequality on rating

### Family 19
- **Variants:** 4 — [19a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/19a.sql), [19b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/19b.sql), [19c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/19c.sql), [19d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/19d.sql)
- **Tables:** aka_name, char_name, cast_info, company_name, info_type, movie_companies, movie_info, name, role_type, title (10)
- **Main JOIN columns:** `t.id = mi/mc/ci.movie_id` + 4-way movie_id clique; `cn.id = mc.company_id`; `it.id = mi.info_type_id`; `n.id = ci.person_id`; `rt.id = ci.role_id`; `n.id = an.person_id`, `ci.person_id = an.person_id`; `chn.id = ci.person_role_id`
- **WHERE predicates:** ci.note IN lists; `cn.country_code = '[us]'`; `it.info = 'release dates'`; mc.note LIKE patterns (19a/b); mi.info LIKE date patterns; `n.gender = 'f'`; n.name LIKE patterns; `rt.role = 'actress'`; t.production_year ranges; `t.title LIKE '%Kung%Fu%Panda%'` (19b)
- **WHERE columns:** cast_info.note, company_name.country_code, info_type.info, movie_companies.note, movie_info.info, name.gender, name.name, role_type.role, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(n.name), MIN(t.title)
- **Structurally similar:** Yes — progressive filter relaxation 19a→19d
- **Unusual:** aka_name and char_name joined but never filtered or projected in WHERE; heavy infix LIKE wildcards

### Family 20
- **Variants:** 3 — [20a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/20a.sql), [20b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/20b.sql), [20c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/20c.sql)
- **Tables:** 10 instances (9 unique): complete_cast, comp_cast_type ×2, char_name, cast_info, keyword, kind_type, movie_keyword, name, title
- **Main JOIN columns:** `kt.id = t.kind_id`, `t.id = mk/ci/cc.movie_id` + 4-way movie_id clique; `chn.id = ci.person_role_id`; `n.id = ci.person_id`; `k.id = mk.keyword_id`; `cct1.id = cc.subject_id`, `cct2.id = cc.status_id`
- **WHERE predicates:** `cct1.kind = 'cast'`; `cct2.kind LIKE '%complete%'`; chn.name LIKE patterns (Tony Stark/Iron Man vs man/Man); keyword IN lists; `kt.kind = 'movie'`; `n.name LIKE '%Downey%Robert%'` (20b); `t.production_year > X`
- **WHERE columns:** comp_cast_type.kind, char_name.name, keyword.keyword, kind_type.kind, name.name, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(t.title) [20a, 20b]; MIN(n.name), MIN(t.title) [20c]
- **Structurally similar:** Yes
- **Unusual:** comp_cast_type joined twice; in 20a name table joined but unfiltered/unprojected; 4-way movie_id clique

### Family 21
- **Variants:** 3 — [21a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/21a.sql), [21b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/21b.sql), [21c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/21c.sql)
- **Tables:** company_name, company_type, keyword, link_type, movie_companies, movie_info, movie_keyword, movie_link, title (9)
- **Main JOIN columns:** `lt.id = ml.link_type_id`, `ml.movie_id = t.id`, `t.id = mk/mc.movie_id`, `mi.movie_id = t.id`, `mk.keyword_id = k.id`, `mc.company_type_id = ct.id`, `mc.company_id = cn.id` + complete 5-way movie_id clique (10 join conditions)
- **WHERE predicates:** `cn.country_code != '[pl]'`; cn.name LIKE patterns; `ct.kind = 'production companies'`; `k.keyword = 'sequel'`; `lt.link LIKE '%follow%'`; `mc.note IS NULL`; mi.info IN country lists; t.production_year BETWEEN ranges
- **WHERE columns:** company_name.country_code, company_name.name, company_type.kind, keyword.keyword, link_type.link, movie_companies.note, movie_info.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn.name), MIN(lt.link), MIN(t.title)
- **Structurally similar:** Yes — differs only in country list and year range
- **Unusual:** K₅ complete clique on movie_id; benchmark typo 'Denish'; movie_link joined on movie_id but no other ml columns used

### Family 22
- **Variants:** 4 — [22a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/22a.sql), [22b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/22b.sql), [22c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/22c.sql), [22d.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/22d.sql)
- **Tables:** 11 instances (10 unique): company_name, company_type, info_type ×2, keyword, kind_type, movie_companies, movie_info, movie_info_idx, movie_keyword, title
- **Main JOIN columns:** `kt.id = t.kind_id`, `t.id = mi/mk/mi_idx/mc.movie_id` + K₅ clique; `k.id = mk.keyword_id`, `it1.id = mi.info_type_id`, `it2.id = mi_idx.info_type_id`, `ct.id = mc.company_type_id`, `cn.id = mc.company_id`
- **WHERE predicates:** `cn.country_code != '[us]'`; `it1.info = 'countries'`; `it2.info = 'rating'`; k.keyword IN murder-related; `kt.kind IN ('movie', 'episode')`; mc.note LIKE/NOT LIKE (22a/b/c); mi.info IN country lists; `mi_idx.info < 'X.X'`; `t.production_year > X`
- **WHERE columns:** company_name.country_code, info_type.info, keyword.keyword, kind_type.kind, movie_companies.note, movie_info.info, movie_info_idx.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn.name), MIN(mi_idx.info), MIN(t.title)
- **Structurally similar:** Yes — 22d drops mc.note filters
- **Unusual:** K₅ complete clique on movie_id; info_type self-joined; company_type joined but never filtered; lexicographic string comparison on rating

### Family 23
- **Variants:** 3 — [23a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/23a.sql), [23b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/23b.sql), [23c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/23c.sql)
- **Tables:** complete_cast, comp_cast_type, company_name, company_type, info_type, keyword, kind_type, movie_companies, movie_info, movie_keyword, title (11)
- **Main JOIN columns:** `kt.id = t.kind_id`, `t.id = mi/mk/mc/cc.movie_id` + K₅ clique on movie_id; `k.id = mk.keyword_id`, `it1.id = mi.info_type_id`, `cn.id = mc.company_id`, `ct.id = mc.company_type_id`, `cct1.id = cc.status_id`
- **WHERE predicates:** `cct1.kind = 'complete+verified'`; `cn.country_code = '[us]'`; `it1.info = 'release dates'`; k.keyword IN (23b only); `kt.kind` IN list; `mi.note LIKE '%internet%'`; mi.info LIKE date patterns; `t.production_year > X`
- **WHERE columns:** comp_cast_type.kind, company_name.country_code, info_type.info, keyword.keyword, kind_type.kind, movie_info.note, movie_info.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(kt.kind), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** company_type joined but unfiltered/unprojected; keyword joined but unfiltered in 23a/23c; K₅ clique on movie_id

### Family 24
- **Variants:** 2 — [24a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/24a.sql), [24b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/24b.sql)
- **Tables:** aka_name, char_name, cast_info, company_name, info_type, keyword, movie_companies, movie_info, movie_keyword, name, role_type, title (12)
- **Main JOIN columns:** `t.id = mi/mc/ci/mk.movie_id` + K₅ movie_id clique (10 conditions); `cn.id = mc.company_id`, `it.id = mi.info_type_id`, `n.id = ci.person_id`, `rt.id = ci.role_id`, `n.id = an.person_id`, `ci.person_id = an.person_id`, `chn.id = ci.person_role_id`, `k.id = mk.keyword_id`
- **WHERE predicates:** ci.note IN voice-related; `cn.country_code = '[us]'`; `cn.name = 'DreamWorks Animation'` (24b); `it.info = 'release dates'`; k.keyword IN martial-arts related; mi.info LIKE date patterns; `n.gender = 'f'`; `n.name LIKE '%An%'`; `rt.role = 'actress'`; `t.production_year > 2010`; `t.title LIKE 'Kung Fu Panda%'` (24b)
- **WHERE columns:** cast_info.note, company_name.country_code, company_name.name, info_type.info, keyword.keyword, movie_info.info, name.gender, name.name, role_type.role, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(chn.name), MIN(n.name), MIN(t.title)
- **Structurally similar:** Yes — 24b adds cn.name and t.title filters
- **Unusual:** One of the largest query graphs (12 tables, 18 join conditions); K₅ movie_id clique + 3-way person_id clique; aka_name joined but never filtered or projected

### Family 25
- **Variants:** 3 — [25a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/25a.sql), [25b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/25b.sql), [25c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/25c.sql)
- **Tables:** 9 instances (8 unique): cast_info, info_type ×2, keyword, movie_info, movie_info_idx, movie_keyword, name, title
- **Main JOIN columns:** `t.id = mi/mi_idx/ci/mk.movie_id` + K₅ complete clique (all 10 pairwise); `n.id = ci.person_id`; `it1.id = mi.info_type_id`; `it2.id = mi_idx.info_type_id`; `k.id = mk.keyword_id`
- **WHERE predicates:** ci.note IN writer roles; `it1.info = 'genres'`; `it2.info = 'votes'`; k.keyword IN murder/violence related; `mi.info = 'Horror'` / IN list (25c); `n.gender = 'm'`; `t.production_year > 2010` (25b); `t.title LIKE 'Vampire%'` (25b)
- **WHERE columns:** cast_info.note, info_type.info, keyword.keyword, movie_info.info, name.gender, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi.info), MIN(mi_idx.info), MIN(n.name), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** K₅ complete clique (10 conditions) on movie_id; info_type self-joined

### Family 26
- **Variants:** 3 — [26a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/26a.sql), [26b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/26b.sql), [26c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/26c.sql)
- **Tables:** 12 instances (11 unique): complete_cast, comp_cast_type ×2, char_name, cast_info, info_type, keyword, kind_type, movie_info_idx, movie_keyword, name, title
- **Main JOIN columns:** `kt.id = t.kind_id`, `t.id = mk/ci/cc/mi_idx.movie_id` + K₅ clique; `chn.id = ci.person_role_id`, `n.id = ci.person_id`, `k.id = mk.keyword_id`, `cct1.id = cc.subject_id`, `cct2.id = cc.status_id`, `it2.id = mi_idx.info_type_id`
- **WHERE predicates:** `cct1.kind = 'cast'`; `cct2.kind LIKE '%complete%'`; chn.name LIKE man/Man patterns; `it2.info = 'rating'`; k.keyword IN superhero/marvel related; `kt.kind = 'movie'`; `mi_idx.info > 'X.X'` (26a/b); `t.production_year > X`
- **WHERE columns:** comp_cast_type.kind, char_name.name, info_type.info, keyword.keyword, kind_type.kind, movie_info_idx.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(chn.name), MIN(mi_idx.info), MIN(n.name) [26a only], MIN(t.title)
- **Structurally similar:** Yes — 26c drops mi_idx.info filter
- **Unusual:** K₅ clique on movie_id; 26b/26c join name but never filter or project it; disjunctive LIKE on character name

### Family 27
- **Variants:** 3 — [27a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/27a.sql), [27b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/27b.sql), [27c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/27c.sql)
- **Tables:** 12 instances (11 unique): complete_cast, comp_cast_type ×2, company_name, company_type, keyword, link_type, movie_companies, movie_info, movie_keyword, movie_link, title
- **Main JOIN columns:** `lt.id = ml.link_type_id`, `ml.movie_id = t.id`, `t.id = mk/mc.movie_id`, `mi.movie_id = t.id`, `t.id = cc.movie_id`, `cct1.id = cc.subject_id`, `cct2.id = cc.status_id`, `mk.keyword_id = k.id`, `mc.company_type_id = ct.id`, `mc.company_id = cn.id` + K₆ clique on movie_id (15 pairwise conditions)
- **WHERE predicates:** `cct1.kind IN ('cast', 'crew')`; `cct2.kind = 'complete'`/LIKE; `cn.country_code != '[pl]'`; cn.name LIKE Film/Warner; `ct.kind = 'production companies'`; `k.keyword = 'sequel'`; `lt.link LIKE '%follow%'`; `mc.note IS NULL`; mi.info IN country lists; t.production_year BETWEEN/=
- **WHERE columns:** comp_cast_type.kind, company_name.country_code, company_name.name, company_type.kind, keyword.keyword, link_type.link, movie_companies.note, movie_info.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn.name), MIN(lt.link), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** **Massive K₆ clique** — 15 pairwise join conditions across 6 tables on movie_id; negative filter `cn.country_code != '[pl]'`; null check `mc.note IS NULL`; typo 'Denish' in 27c; misleading alias `complete_western_sequel`

### Family 28
- **Variants:** 3 — [28a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/28a.sql), [28b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/28b.sql), [28c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/28c.sql)
- **Tables:** 14 instances (12 unique): complete_cast, comp_cast_type ×2, company_name, company_type, info_type ×2, keyword, kind_type, movie_companies, movie_info, movie_info_idx, movie_keyword, title
- **Main JOIN columns:** `kt.id = t.kind_id`, `t.id = mi/mk/mi_idx/mc/cc.movie_id` + K₆ clique (15 conditions); `k.id = mk.keyword_id`, `it1.id = mi.info_type_id`, `it2.id = mi_idx.info_type_id`, `ct.id = mc.company_type_id`, `cn.id = mc.company_id`, `cct1.id = cc.subject_id`, `cct2.id = cc.status_id`
- **WHERE predicates:** `cct1.kind = 'crew'/'cast'`; `cct2.kind != 'complete+verified'` / `= 'complete'`; `cn.country_code != '[us]'`; `it1.info = 'countries'`; `it2.info = 'rating'`; k.keyword IN murder-related; `kt.kind IN ('movie', 'episode')`; mc.note NOT LIKE/LIKE patterns; mi.info IN country lists; `mi_idx.info < '8.5'` / `> '6.5'`; `t.production_year > X`
- **WHERE columns:** comp_cast_type.kind, company_name.country_code, info_type.info, keyword.keyword, kind_type.kind, movie_companies.note, movie_info.info, movie_info_idx.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn.name), MIN(mi_idx.info), MIN(t.title)
- **Structurally similar:** Yes
- **Unusual:** K₆ clique on movie_id; both comp_cast_type and info_type instantiated twice; multiple negative predicates; simultaneous positive and negative LIKE on mc.note

### Family 29
- **Variants:** 3 — [29a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/29a.sql), [29b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/29b.sql), [29c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/29c.sql)
- **Tables:** **17 instances (15 unique)**: aka_name, complete_cast, comp_cast_type ×2, char_name, cast_info, company_name, info_type ×2, keyword, movie_companies, movie_info, movie_keyword, name, person_info, role_type, title
- **Main JOIN columns:** K₆ clique on movie_id (t, mi, mc, ci, mk, cc: 15 pairwise joins); K₄ clique on person_id (n, ci, an, pi); `chn.id = ci.person_role_id`; `rt.id = ci.role_id`; `cn.id = mc.company_id`; `it.id = mi.info_type_id`; `it3.id = pi.info_type_id`; `cct1.id = cc.subject_id`; `cct2.id = cc.status_id`; `k.id = mk.keyword_id`
- **WHERE predicates:** `cct1.kind = 'cast'`; `cct2.kind = 'complete+verified'`; `chn.name = 'Queen'` (29a/b); ci.note IN voice-related; `cn.country_code = '[us]'`; `it.info = 'release dates'`; `it3.info = 'trivia'/'height'`; `k.keyword = 'computer-animation'`; mi.info LIKE patterns; `n.gender = 'f'`; `n.name LIKE '%An%'`; `rt.role = 'actress'`; `t.title = 'Shrek 2'` (29a/b); t.production_year BETWEEN
- **WHERE columns:** comp_cast_type.kind, char_name.name, cast_info.note, company_name.country_code, info_type.info, keyword.keyword, movie_info.info, name.gender, name.name, role_type.role, title.title, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(chn.name), MIN(n.name), MIN(t.title)
- **Structurally similar:** Yes — 29c drops title and character name filters (dramatic selectivity change)
- **Unusual:** **Largest queries in the benchmark** (17 table instances, 15 unique tables, 28 join conditions); dual cliques (K₆ on movie_id, K₄ on person_id); 29a/29b are near point-lookups ('Shrek 2', 'Queen'), 29c is a broad scan

### Family 30
- **Variants:** 3 — [30a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/30a.sql), [30b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/30b.sql), [30c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/30c.sql)
- **Tables:** 12 instances (10 unique): complete_cast, comp_cast_type ×2, cast_info, info_type ×2, keyword, movie_info, movie_info_idx, movie_keyword, name, title
- **Main JOIN columns:** K₆ clique on movie_id (t, ci, mi, mi_idx, mk, cc: 15 conditions); `n.id = ci.person_id`; `it1.id = mi.info_type_id`; `it2.id = mi_idx.info_type_id`; `k.id = mk.keyword_id`; `cct1.id = cc.subject_id`; `cct2.id = cc.status_id`
- **WHERE predicates:** cct1.kind IN ('cast', 'crew') or = 'cast'; `cct2.kind = 'complete+verified'`; ci.note IN writer roles; `it1.info = 'genres'`; `it2.info = 'votes'`; k.keyword IN violence-related; mi.info IN genre lists; `n.gender = 'm'`; `t.production_year > 2000` (30a/b); t.title LIKE franchise patterns (30b)
- **WHERE columns:** comp_cast_type.kind, cast_info.note, info_type.info, keyword.keyword, movie_info.info, name.gender, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi.info), MIN(mi_idx.info), MIN(n.name), MIN(t.title)
- **Structurally similar:** Yes — 30b adds title LIKE; 30c drops year filter and narrows cct1
- **Unusual:** K₆ clique on movie_id; both comp_cast_type and info_type instantiated twice; disjunctive franchise title LIKE patterns in 30b

### Family 31
- **Variants:** 3 — [31a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/31a.sql), [31b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/31b.sql), [31c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/31c.sql)
- **Tables:** 11 instances (10 unique): cast_info, company_name, info_type ×2, keyword, movie_companies, movie_info, movie_info_idx, movie_keyword, name, title
- **Main JOIN columns:** K₆ clique on movie_id (t, ci, mi, mi_idx, mk, mc: 15 conditions); `n.id = ci.person_id`; `it1.id = mi.info_type_id`; `it2.id = mi_idx.info_type_id`; `k.id = mk.keyword_id`; `cn.id = mc.company_id`
- **WHERE predicates:** ci.note IN writer roles; `cn.name LIKE 'Lionsgate%'`; `it1.info = 'genres'`; `it2.info = 'votes'`; k.keyword IN violence-related; mc.note LIKE patterns (31b); mi.info IN genre lists; `n.gender = 'm'` (31a/b); `t.production_year > 2000` (31b); t.title LIKE franchise patterns (31b)
- **WHERE columns:** cast_info.note, company_name.name, info_type.info, keyword.keyword, movie_companies.note, movie_info.info, name.gender, title.production_year, title.title
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(mi.info), MIN(mi_idx.info), MIN(n.name), MIN(t.title)
- **Structurally similar:** Yes — 31c drops n.gender filter and widens genre list
- **Unusual:** K₆ clique on movie_id; 31c joins name table but leaves it unfiltered while still projecting MIN(n.name); info_type self-joined; prefix + substring LIKE patterns in 31b

### Family 32
- **Variants:** 2 — [32a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/32a.sql), [32b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/32b.sql)
- **Tables:** 6 instances (5 unique): keyword, link_type, movie_keyword, movie_link, title ×2
- **Main JOIN columns:** `mk.keyword_id = k.id`, `t1.id = mk.movie_id`, `ml.movie_id = t1.id`, `ml.linked_movie_id = t2.id`, `lt.id = ml.link_type_id`
- **WHERE predicates:** `k.keyword = '10,000-mile-club'` (32a) / `'character-name-in-title'` (32b)
- **WHERE columns:** keyword.keyword
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(lt.link), MIN(t1.title), MIN(t2.title)
- **Potential indexable columns:** keyword(keyword, id), movie_keyword(keyword_id, movie_id), movie_link(movie_id, linked_movie_id, link_type_id), title(id), link_type(id)
- **Structurally similar:** Yes — identical structure, single keyword value changes
- **Unusual:** **Self-join on title** (t1 and t2 via movie_link); minimal filtering — entire 6-table graph filtered by one equality predicate; redundant join predicate

### Family 33
- **Variants:** 3 — [33a.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/33a.sql), [33b.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/33b.sql), [33c.sql](file:///C:/Users/Sagar/Desktop/ml-postgresql-index-advisor/benchmarks/job/33c.sql)
- **Tables:** **14 instances (8 unique)**: company_name ×2, info_type ×2, kind_type ×2, link_type, movie_companies ×2, movie_info_idx ×2, movie_link, title ×2
- **Main JOIN columns:** `lt.id = ml.link_type_id`; Movie 1 cluster: `t1.id = ml.movie_id`, `t1.id = mi_idx1/mc1.movie_id`, `kt1.id = t1.kind_id`, `cn1.id = mc1.company_id`, `it1.id = mi_idx1.info_type_id` + 3-way movie_id clique; Movie 2 cluster: `t2.id = ml.linked_movie_id`, `t2.id = mi_idx2/mc2.movie_id`, `kt2.id = t2.kind_id`, `cn2.id = mc2.company_id`, `it2.id = mi_idx2.info_type_id` + 3-way movie_id clique
- **WHERE predicates:** `cn1.country_code = '[us]'/'[nl]'/!='[us]'`; `it1.info = 'rating'`; `it2.info = 'rating'`; `kt1.kind IN ('tv series')` / extended; `kt2.kind IN ('tv series')` / extended; `lt.link IN ('sequel', 'follows', 'followed by')` / LIKE; `mi_idx2.info < '3.0'/'3.5'`; `t2.production_year BETWEEN / =`
- **WHERE columns:** company_name.country_code, info_type.info, kind_type.kind, link_type.link, movie_info_idx.info, title.production_year
- **GROUP BY:** None | **ORDER BY:** None
- **Aggregates:** MIN(cn1.name), MIN(cn2.name), MIN(mi_idx1.info), MIN(mi_idx2.info), MIN(t1.title), MIN(t2.title)
- **Structurally similar:** Yes
- **Unusual:** **Symmetric dual-subgraph topology** — 6 tables instantiated twice representing movie 1 and movie 2, connected through movie_link/link_type; **asymmetric filtering** (only cn1 country code filtered, only t2 year and mi_idx2 rating filtered); negation filter in 33c (`!= '[us]'`); lexicographic string comparison on rating

---

## Section 3 — Aggregate Statistics

| Metric | Count |
|--------|-------|
| **Total families analyzed** | **33** |
| **Total query variants analyzed** | **113** |
| Families containing JOINs | **33** (100%) |
| Families containing WHERE predicates | **33** (100%) |
| Families containing GROUP BY | **0** (0%) |
| Families containing ORDER BY | **0** (0%) |
| Families containing aggregate functions | **33** (100%) — all use MIN() |

### Variant Counts Per Family

| Family | Variants | | Family | Variants | | Family | Variants |
|--------|----------|-|--------|----------|-|--------|----------|
| 1 | 4 | | 12 | 3 | | 23 | 3 |
| 2 | 4 | | 13 | 4 | | 24 | 2 |
| 3 | 3 | | 14 | 3 | | 25 | 3 |
| 4 | 3 | | 15 | 4 | | 26 | 3 |
| 5 | 3 | | 16 | 4 | | 27 | 3 |
| 6 | 6 | | 17 | 6 | | 28 | 3 |
| 7 | 3 | | 18 | 3 | | 29 | 3 |
| 8 | 4 | | 19 | 4 | | 30 | 3 |
| 9 | 4 | | 20 | 3 | | 31 | 3 |
| 10 | 3 | | 21 | 3 | | 32 | 2 |
| 11 | 4 | | 22 | 4 | | 33 | 3 |

**Total:** 4+4+3+3+3+6+3+4+4+3+4+3+4+3+4+4+6+3+4+3+3+4+3+2+3+3+3+3+3+3+3+2+3 = **113** ✓

### Complexity Distribution

| Complexity | Families | Count |
|------------|----------|-------|
| **Medium** | 1, 2, 3, 4, 5, 6, 32 | **7** |
| **High** | 7–31, 33 | **26** |

### Cross-Cutting Observations

- **All 113 queries are SELECT queries** with no INSERT/UPDATE/DELETE.
- **All queries use only MIN() aggregates** — no SUM, COUNT, AVG, or MAX.
- **No GROUP BY or ORDER BY** appears in any query. All produce a single aggregated row.
- **Every family uses multi-table JOINs.** Table count ranges from 4 (family 3) to 17 instances (family 29).
- **Redundant join cliques** (explicit transitive equalities on movie_id, person_id) are pervasive across almost all families. Many queries include complete K₄, K₅, or K₆ cliques.
- **Self-joins / multiple aliasing** is common: `info_type`, `comp_cast_type`, `title`, `company_name`, `kind_type`, `movie_companies`, `movie_info_idx` are frequently instantiated more than once.
- **Variants within each family are structurally nearly identical**, differing primarily in filter literal values, selectivity ranges, and occasionally the presence/absence of individual predicates.
- **LIKE patterns with leading wildcards** (e.g., `'%sequel%'`, `'%Downey%Robert%'`) are very common, making them un-indexable for B-tree indexes.
- **String inequality on numeric data** (e.g., `mi_idx.info > '8.0'`) appears in multiple families (4, 12, 14, 18, 22, 25, 26, 28, 33) due to ratings stored as text.
- **Benchmark typo** `'Denish'` instead of `'Danish'` appears across families 3, 5, 14, 21, 27.
- **Tables joined but never filtered or projected** (phantom joins) appear in many families, acting as existence semi-joins.

---

### Verification

- ✅ 33 families analyzed
- ✅ 113 query variants inspected
- ✅ All data derived from actual SQL files in `benchmarks/job/`
- ✅ No modifications made to the repository
