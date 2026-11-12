from magister_api.services.upn_domains import domain_of_search_base


def test_domain_comes_from_the_dc_parts_of_the_search_base() -> None:
    assert domain_of_search_base("OU=Benutzer, DC=Schule ,DC=local") == "schule.local"
    assert domain_of_search_base("DC=ad,DC=gemeinde,DC=ch") == "ad.gemeinde.ch"
    assert domain_of_search_base("OU=Benutzer") is None
    assert domain_of_search_base(None) is None
