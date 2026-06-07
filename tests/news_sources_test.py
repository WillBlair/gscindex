import unittest


from data.news_sources import NEWS_SOURCES, SOURCE_GROUPS, get_sources_by_group


class NewsSourcesTests(unittest.TestCase):
    def test_news_sources_have_required_fields(self):
        for source in NEWS_SOURCES:
            self.assertTrue(source["name"])
            self.assertTrue(source["url"].startswith(("http://", "https://")))
            self.assertIn(source["group"], SOURCE_GROUPS)
            self.assertIsInstance(source["max_items"], int)
            self.assertGreater(source["max_items"], 0)

    def test_source_groups_include_official_risk_buckets(self):
        self.assertTrue(
            {
                "logistics_trade",
                "ports_shipping",
                "trade_policy",
                "weather_disasters",
            }.issubset(SOURCE_GROUPS)
        )

    def test_get_sources_by_group_filters_without_mutating(self):
        logistics = get_sources_by_group("logistics_trade")

        self.assertTrue(logistics)
        self.assertTrue(all(source["group"] == "logistics_trade" for source in logistics))
        self.assertIsNot(logistics, NEWS_SOURCES)


if __name__ == "__main__":
    unittest.main()
