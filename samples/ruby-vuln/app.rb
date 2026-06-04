# Ruby vulnerable dependencies sample
# CVEs: rails 5.2.0, nokogiri 1.10.0, rack 2.0.8

require 'nokogiri'

# CVE-2022-24836: Nokogiri heap buffer overflow via crafted HTML
def parse_html(content)
  Nokogiri::HTML(content)
end

# CVE-2020-26247: Nokogiri XXE via stylesheet
def parse_xml(xml)
  Nokogiri::XML(xml)
end
