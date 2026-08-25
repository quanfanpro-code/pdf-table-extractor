from app.extractors.registry import iter_local_extractors


def test_registry_discovers_all_local_extractors_without_routing_list():
    extractors = iter_local_extractors()
    labels = [label for label, _extractor in extractors]

    assert {"成都农商行", "民生银行", "华夏银行", "普通表格"} <= set(labels)
    assert labels[-1] == "普通表格"
    assert all(callable(extractor) for _label, extractor in extractors)
