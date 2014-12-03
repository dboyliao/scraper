from scrapy.contrib.spiders import CrawlSpider
from scrapy.http.request import Request
from scrapy.http import FormRequest

from scraper.items import ProductItem

from copy import deepcopy
import re, lxml

class MyBabyWarehouseSpider(CrawlSpider):
	"""
	Spider for http://mybabywarehouse.com.au/
	"""
	name = "mybabywarehouse"
	source = "http://mybabywarehouse.com.au/"
	start_urls = [
		source,
	]

	product_number_pattern = re.compile("[0-9]{1,}")
	
	# get_product_price_pattern1: normal product page.
	# get_product_price_pattern2: product page with special price.
	# get_product_price_pattern3: product page with different sizes
	# of product. (ex: cloth)
	# get_product_table is used when there is a product table in the 
	# product page.
	#
	# example: 
	#     http://mybabywarehouse.com.au/baby-bedding/sleeping-bags/grobag-travel-sleeping-bag-teapot-regatta.html
	# Note: the information of products in a product table
	#       may differ.
	#      http://mybabywarehouse.com.au/baby-bedding/sleeping-bags/grobag-travel-sleeping-bag-teapot-regatta.html
	xpaths = {
		"get_categories":"//nav[@id='nav']/ol[@class='nav-primary']/li/a[@class='level0 has-children']",
		"get_subcategories":"//dt[text()='Category']/following-sibling::dd[1]/ol/li/a",
		"get_products":"//div[@class='category-products']/ul/li/a",
		"get_product_number":"//div/input[@name='product']/@value",
		"get_product_name":"//div[@class='product-name']/span/text()",
		"get_product_image_url": "//p[@class='product-image']//img/@src",
		"get_product_table":"//div[@class='grouped-items-table-wrapper']/table",
		"get_product_price_pattern1": "//div[@class='price-box']//span[@id='product-price-{product_number}']//span[@class='price']/text()",
		"get_product_price_pattern2": "//div[@class='price-info']//span[@id='product-price-{product_number}']/text()",
		"get_product_price_pattern3": "//span[@id='product-price-{product_number}']/span/text()",
		"get_description":"//div[@class='product-collateral toggle-content tabs']/div[@class='std']",
		"get_category_name": "//div[@class='bread_bg']/div[@id='site-container']//li",
		"get_manufacturer": "//table[@id='product-attribute-specs-table']//th[text()='Brand']/following-sibling::td/text()"
	}

	def parse(self, response):
		category_pages = response.xpath(self.xpaths["get_categories"])
		for category_page in category_pages:
			category_paths = ["Home"]
			category_name = category_page.xpath("text()").extract()[0].strip()
			category_paths.append(category_name)
			# Browsing category page.
			category_url = category_page.xpath("@href").extract()[0]
			meta = {"category_paths": category_paths}
			yield Request(
				url = category_url,
				meta = deepcopy(meta),
				callback = self.parse_category)

	def parse_category(self, response):
		subcategory_pages = response.xpath(self.xpaths["get_subcategories"])
		for subcategory_page in subcategory_pages:
			# Add subcategory name to category_paths
			temp_category_paths = deepcopy(response.meta["category_paths"])
			subcategory_name = subcategory_page.xpath("text()").extract()[0].strip()
			temp_category_paths.append(subcategory_name)
			meta = {"category_paths": temp_category_paths}

			subcategory_url = subcategory_page.xpath("@href").extract()[0].replace("?___SID=U", "") + "?limit=all"
			
			yield Request(
				url = subcategory_url,
				meta = meta,
				callback = self.parse_sub_category)

	def parse_sub_category(self, response):
		products = response.xpath(self.xpaths["get_products"])
		for product in products:
			product_url = product.xpath("@href").extract()[0]
			meta = deepcopy(response.meta)
			yield Request(
				url = product_url,
				meta = meta,
				callback = self.parse_product)

	def parse_product(self, response):

		item = ProductItem()
		# source
		source = self.source

		# category_name
		category_paths = response.meta["category_paths"]
		category_name = ProductItem.CG_PATH_SEP.join(category_paths)

		# product_url
		product_url = response.url

		# image_url: full-size picture
		image_url = response.xpath(self.xpaths["get_product_image_url"])

		# description
		description_text = response.xpath(self.xpaths["get_description"]).extract()[0]
		description = lxml.html.fromstring(description_text.replace("<br>", "\n")).text_content().strip()

		# currency
		currency = "AUD"

		# availability
		availability = ProductItem.AVAIL_IS

		# manufacturer
		manufacturer = response.xpath(self.xpaths["get_manufacturer"]).extract()[0]

		# product_condition
		product_condition = ProductItem.PC_NEW

		# 1. Check whether there is a product table.
		# 2. If there is a table, use pattern3.
		# 3. Else, pass it to pattern 1 and 2.
		product_table = response.xpath(self.xpaths["get_product_table"])
		if len(product_table):
			products = response.xpath(self.xpaths["get_product_table"] + "//tr")
			for product in products:
				# Iterate through products contained in the table.
				item = ProductItem()

				item["source"] = source

				item["category_name"] = category_name

				item["image_url"] = image_url.extract()[0]

				product_name = product.xpath("td[@class='name']/p/text()").extract()[0].strip()
				item["product_name"] = product_name

				item["description"] = description

				item["category_name"] = category_name

				item["product_url"] = response.url

				item["currency"] = currency

				item["product_condition"] = product_condition

				product_numbers = product.xpath("td//div[@class='price-box']/span/@id").extract()
				if len(product_numbers) > 1:
					raise ValueError("Multiple product numbers are found.")
				elif len(product_numbers) == 0:
					raise ValueError("No product number is found.")
				else:
					product_number = self.product_number_pattern.findall(product_numbers[0])[0]
					item["product_number"] = product_number

				product_price = response.xpath(self.xpaths["get_product_price_pattern3"].format(product_number = product_number))
				item["sale_price"] = float(product_price.extract()[0].strip().strip("$").replace(",", ""))

				item["availability"] = availability

				item["on_sale"] = 0

				item["shipping_cost"] = -1

				item["manufacturer"] = manufacturer

				yield item


				

		else:
			item = ProductItem()

			# source
			item["source"] = source

			# category_name
			item["category_name"] = category_name

			# product_number
			product_number = response.xpath(self.xpaths["get_product_number"]).extract()[0]
			item["product_number"] = product_number

			# product_name
			product_name = response.xpath(self.xpaths["get_product_name"]).extract()[0]
			item["product_name"] = product_name

			# description
			item["description"] = description

			# currency
			item["currency"] = currency
			
			# product_url
			item["product_url"] = product_url

			# img_url
			img_url = response.xpath(self.xpaths["get_product_image_url"])
			item["image_url"] = image_url.extract()[0]

			# product_condition
			item["product_condition"] = product_condition

			# availability
			item["availability"] = availability

			# sale_price
			# 1. Check it is a normal product page.
			# 2. If it is not a normal product page, go for pattern2.
			sale_price = response.xpath(self.xpaths["get_product_price_pattern1"].format(product_number = product_number))
			if len(sale_price):
				item["sale_price"] = float(sale_price.extract()[0].strip().strip("$").replace(",", ""))
				item["on_sale"] = 0
			else:
				sale_price = response.xpath(self.xpaths["get_product_price_pattern2"].format(product_number = product_number))
				item["sale_price"] = float(sale_price.extract()[0].strip().strip("$").replace(",", ""))
				item["on_sale"] = 1

			item["shipping_cost"] = -1

			item["manufacturer"] = manufacturer

			yield item
