from scrapy.contrib.spiders import CrawlSpider
from scrapy.http.request import Request
from scrapy.http import FormRequest

from scraper.items import ProductItem

from copy import deepcopy
import re, lxml

class PramwareHouseSpider(CrawlSpider):
	"""
	Spider for http://pramwarehouse.com.au/
	"""
	name = "pramwarehouse"
	source = "http://pramwarehouse.com.au/"
	start_urls = [
		source,
	]

	find_zero_percent_pattern = re.compile("^0.00%")
	find_pnumber_pattern = re.compile("pid/[0-9]{1,}")

	# 1. It is possible for some category to have no subcategory.
	# 2. It is possible for some subcategory page to have no products.
	#   ex: http://pramwarehouse.com.au/cateitem/listcate/cname/All_the_Way_08Years_NEW.html
	xpaths = {
		"get_category_pages": "//div[@class='topmenu']/ul/li/a",
		"get_subcategory_pages": "//div[@class='grtabs']/a",
		"get_product_pages": "//div[@class='item']/div[1][@class='img']/a",
		"get_pagination": "//div[@class='headline normal'][1]/div[@class='pagination']/font/font/text()",
		"get_product_name": "//div[@id='mainTemplateSection']//div[@class='desc']/h2/text()",
		"get_product_price": "//div[@class='blue']/text()",
		"get_next_page": "//div[contains(@class, 'headline')][1]/div[@class='pagination']/a[text()='next']",
		"get_last_page": "//div[contains(@class, 'headline')][1]/div[@class='pagination']/a[text()='last page']",
		"get_image_url": "//img[@id='galleryTarget']/@src",
		"get_description": "//li[@id='cfeature']//font",
		"get_manufacturer": "//div[@class='product']/div[@class='desc']/h3/text()",
		"get_discount": "//div[@id='mainTemplateSection']//div[@class='green']/text()",
		"get_options_block":"//form[@id='prodform']/span",
		"get_add_to_cart": "//div[@id='mainTemplateSection']//div[@class='descin pad10']/div/a[@class='button'][1]",
		"get_checkout": "//a[@id='gCheckOut']/@onclick"
	}

	def parse(self, response):
		# drop the first category page since it is the home page.
		category_pages = response.xpath(self.xpaths["get_category_pages"])[1:]
		for category_page in category_pages:
			category_paths = ["Home"]
			category_url = self.source + category_page.xpath("@href").extract()[0]
			category_name = category_page.xpath("text()").extract()[0]
			category_paths.append(category_name)
			meta = {"category_paths": category_paths}
			yield Request(
				url = category_url,
				meta = meta,
				callback = self.parse_category
			)

	def parse_category(self, response):
		subcategory_pages = response.xpath(self.xpaths["get_subcategory_pages"])
		for subcategory_page in subcategory_pages:
			
			# Updating category_paths.
			category_paths = deepcopy(response.meta["category_paths"])
			subcategory_name = subcategory_page.xpath("text()").extract()[0]
			category_paths.append(subcategory_name)

			# Get subcategory url. 
			subcategory_url = self.source + subcategory_page.xpath("@href").extract()[0]
			meta = {"category_paths" : category_paths}

			# Generate request.
			yield Request(
				url = subcategory_url,
				meta = meta,
				callback = self.parse_subcategory 
				)

	def parse_subcategory(self, response):
		product_pages = response.xpath(self.xpaths["get_product_pages"])
		meta = response.meta
		for product_page in product_pages:
			product_url = self.source + product_page.xpath("@href").extract()[0]
			yield Request(
				url = product_url,
				meta = meta,
				callback = self.parse_product
				)
		# Checking whether there is a next page or not.
		next_page = response.xpath(self.xpaths["get_next_page"])[0]
		last_page = response.xpath(self.xpaths["get_last_page"])[0]
		next_page_url = self.source + next_page.xpath("@href").extract()[0]
		last_page_url = self.source + last_page.xpath("@href").extract()[0]
		paginate = response.xpath(self.xpaths["get_pagination"])
		total_page = paginate[1].extract()
		if total_page not in (u"1", u"0"):
			if next_page_url != last_page_url or response.url != next_page_url:
				yield Request(
					url = next_page_url,
					meta = meta,
					callback = self.parse_subcategory
					)

	def parse_product(self, response):

		# availability
		add_to_cart = response.xpath(self.xpaths["get_add_to_cart"])
		if len(add_to_cart.extract()):
			availability = ProductItem.AVAIL_IS
		else:
			availability = ProductItem.AVAIL_OOS

		# product_number (if there is no options)
		checkout = response.xpath(self.xpaths["get_checkout"])
		product_number = self.find_pnumber_pattern.findall(checkout.extract()[0])[0].split("/")[1]

		# product_name
		product_name = response.xpath(self.xpaths["get_product_name"]).extract()[0]

		# category_name
		category_paths = response.meta["category_paths"]
		category_name = ProductItem.CG_PATH_SEP.join(category_paths)

		# image_url: full-size picture
		image_url = self.source + response.xpath(self.xpaths["get_image_url"]).extract()[0]

		# description
		description_lines = map(
			lambda line: line.text_content().strip(),
			map(
				lxml.html.fromstring,
				response.xpath(self.xpaths["get_description"]).extract()
				)
			)
		description = "\n".join(description_lines)

		# sale_price
		sale_price = response.xpath(self.xpaths["get_product_price"]).extract()[0]
		sale_price = float(sale_price.strip().strip("$").replace(",", ""))

		# manufacturer
		tmp = response.xpath(self.xpaths["get_manufacturer"]).extract()
		if len(tmp):
			manufacturer = tmp[0]
		else:
			manufacturer = product_name.split(" ")[0].title()

		# on_sale
		discount = response.xpath(self.xpaths["get_discount"]).extract()[0]
		if len(self.find_zero_percent_pattern.findall(discount)):
			on_sale = 0
		else:
			on_sale = 1

		# Check whether there is options or not.
		options_block = response.xpath(self.xpaths["get_options_block"])
		if len(options_block):
			option_names = options_block.xpath("span/text()").extract()
			option_numbers = options_block.xpath("input/@value").extract()
			assert len(option_names) == len(option_numbers), "Option names and Option numbers does not match."
			for option_name, option_number in zip(option_names, option_numbers):
				item = ProductItem()

				# source
				item["source"] = self.source

				# category_name
				item["category_name"] = category_name

				# product_number
				item["product_number"] = product_number + "-" + option_number

				# product_name
				item["product_name"] = product_name + " - " + option_name

				# product_url
				item["product_url"] = response.url

				# image_url
				item["image_url"] = image_url

				# description
				item["description"] = description

				# currency
				item["currency"] = "AUD"

				# manufacturer
				item["manufacturer"] = manufacturer

				# product_condition
				item["product_condition"] = ProductItem.PC_NEW

				# sale_price
				item["sale_price"] = sale_price

				# availability
				item["availability"] = availability

				# on_sale
				item["on_sale"] = on_sale

				# shipping cost
				item["shipping_cost"] = -1

				yield item
		else:
			item = ProductItem()

			item["source"] = self.source

			item["category_name"] = category_name

			item["product_name"] = product_name

			item["product_number"] = product_number

			item["product_url"] = response.url

			item["image_url"] = image_url

			item["description"] = description

			item["currency"] = "AUD"

			item["manufacturer"] = manufacturer

			item["product_condition"] = ProductItem.PC_NEW

			item["sale_price"] = sale_price

			item["availability"] = availability

			item["on_sale"] = on_sale

			item["shipping_cost"] = -1

			yield item



	# def parse_shipping_cost(self, response):
	# 	pass
