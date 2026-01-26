# # app/seed_data/print_formats/formats.py
# from __future__ import annotations
#
# from typing import List, Dict, Any
#
#
#
# # ----------------------------------------------------------------------
# # SALES INVOICE - DJIBOUTI (Frappe-like custom) - GLOBAL DEFAULT
# # Uses your layout and DJF formatting, but mapped to your load_sales_invoice() JSON shape.
# # ----------------------------------------------------------------------
# SALES_INVOICE_DJIBOUTI_HTML = r"""
# {% set basic = doc.get('basic_details', {}) %}
# {% set party = doc.get('party_and_branch', {}) %}
# {% set fin = doc.get('financial_summary', {}) %}
# {% set meta = doc.get('meta', {}) %}
# {% set pay = doc.get('payments_and_taxes', {}) %}
# {% set line_items = doc.get('items', []) %}
#
# {% macro djf_currency(value) -%}
#   {{ "{:,.0f}".format(value or 0) }} DJF
# {%- endmacro %}
#
# <div style="font-family: Arial, sans-serif; margin:0; padding:0;">
#   <div style="width:700px; margin: 0 auto; padding:10px; box-sizing:border-box;">
#
#     <!-- HEADER -->
#     <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:20px;">
#       <div>
#         {{ letter_head or "" }}
#       </div>
#
#       <div>
#         <h1 style="text-align:center; margin-bottom:8px;">Sales Invoice</h1>
#         <div style="text-align:center; margin-bottom:20px; font-size:0.9em; line-height:1.4;">
#           <div>Saline West, Konya Road, Djibouti</div>
#           <div>Email: info@cis-age.com</div>
#           <div>Phone: +253 77 15 34 06</div>
#         </div>
#       </div>
#     </div>
#
#     <!-- BILL TO & META -->
#     <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
#       <div style="width:48%; font-size:0.9em; line-height:1.4;">
#         <strong>BILL TO:</strong><br>
#         Student Name: {{ party.get('customer_name', '') }}<br>
#         Grade: {{ meta.get('custom_program') or basic.get('custom_program') or '' }}<br>
#       </div>
#
#       <div style="width:48%; text-align:right; font-size:0.9em; line-height:1.4;">
#         <div><strong>Sales Invoice NO.:</strong>
#           {{ basic.get('doc_no') or basic.get('code') or basic.get('id') or '' }}
#         </div>
#         <div><strong>DATE:</strong> {{ basic.get('posting_date', '') }}</div>
#       </div>
#     </div>
#
#     <!-- ITEMS -->
#     <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
#       <thead>
#         <tr>
#           <th style="border:1px solid #000; padding:6px; text-align:left;">Description</th>
#           <th style="border:1px solid #000; padding:6px; text-align:right;">Qty</th>
#           <th style="border:1px solid #000; padding:6px; text-align:right;">Amount</th>
#         </tr>
#       </thead>
#       <tbody>
#
#         {% set ns = namespace(sub_total=0) %}
#         {% set dis = namespace(discount=0) %}
#         {% set disa = namespace(dis_amount=0) %}
#
#         {% if line_items %}
#           {% for it in line_items %}
#             {% set rate = it.get('price_list_rate') if it.get('price_list_rate') is not none else it.get('rate') %}
#             {% set qty  = it.get('quantity') if it.get('quantity') is not none else it.get('qty') %}
#             {% set disc_pct = it.get('discount_percentage', 0) %}
#             {% set disc_amt = it.get('discount_amount', 0) %}
#
#             {% set ns.sub_total = ns.sub_total + (rate or 0) %}
#             {% set dis.discount = dis.discount + (disc_pct or 0) %}
#             {% set disa.dis_amount = disa.dis_amount + (disc_amt or 0) %}
#
#             <tr>
#               <td style="border:1px solid #000; padding:6px;">
#                 {{ it.get('item_code') or it.get('item_name') or '' }}
#               </td>
#               <td style="border:1px solid #000; padding:6px; text-align:right;">
#                 {{ qty or 0 }}
#               </td>
#               <td style="border:1px solid #000; padding:6px; text-align:right;">
#                 {{ djf_currency(rate) }}
#               </td>
#             </tr>
#           {% endfor %}
#         {% else %}
#           <tr>
#             <td colspan="3" style="text-align:center; padding:6px;">
#               No items available
#             </td>
#           </tr>
#         {% endif %}
#
#       </tbody>
#     </table>
#
#     <!-- TOTALS -->
#     <div style="width:100%; display:flex; justify-content:flex-end; margin-bottom:20px;">
#       <table style="width:300px; border-collapse:collapse;">
#         <tbody>
#           <tr>
#             <td style="padding:6px;">Subtotal</td>
#             <td style="padding:6px; text-align:right;">
#               {{ djf_currency(ns.sub_total) }}
#             </td>
#           </tr>
#           <tr>
#             <td style="padding:6px;">Discount {{ dis.discount }}%</td>
#             <td style="padding:6px; text-align:right;">
#               {{ djf_currency(disa.dis_amount) }}
#             </td>
#           </tr>
#           <tr>
#             <td style="padding:6px; font-weight:bold;">Total</td>
#             <td style="padding:6px; text-align:right; font-weight:bold;">
#               {{ djf_currency(ns.sub_total - disa.dis_amount) }}
#             </td>
#           </tr>
#         </tbody>
#       </table>
#     </div>
#
#     <!-- PAYMENT SCHEDULE -->
#     {% if pay.get('payment_schedule') %}
#       <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
#         <thead>
#           <tr>
#             <th style="border:1px solid #000; padding:3px; text-align:left;">Payment Term</th>
#             <th style="border:1px solid #000; padding:3px; text-align:right;">Due Date</th>
#             <th style="border:1px solid #000; padding:3px; text-align:right;">
#               Payment Amount (DJF)
#             </th>
#           </tr>
#         </thead>
#         <tbody>
#           {% for row in pay.get('payment_schedule') %}
#             <tr>
#               <td style="border:1px solid #000; padding:3px;">
#                 {{ row.get('payment_term') }}
#               </td>
#               <td style="border:1px solid #000; padding:3px; text-align:right;">
#                 {{ row.get('due_date') }}
#               </td>
#               <td style="border:1px solid #000; padding:3px; text-align:right;">
#                 {{ djf_currency(row.get('payment_amount')) }}
#               </td>
#             </tr>
#           {% endfor %}
#         </tbody>
#       </table>
#     {% endif %}
#
#     <!-- FOOTER -->
#     <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
#       <strong>Payment Terms:</strong><br>
#       <strong>Methods:</strong> Cash | Bank Transfer
#     </div>
#
#     <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
#       <strong>Bank Details:</strong><br>
#       CAC Islamic Bank — 77000000212 <br>
#       CAC Pay — 103002<br><br>
#       Salaam African Bank — 10513889<br>
#       Waafi — 7720
#     </div>
#
#     <div style="display:flex; justify-content:space-between; margin-top:40px; font-size:0.9em;">
#       <div>
#         <strong>Authorized By:</strong><br>
#         <strong>Position:</strong>
#       </div>
#       <div style="text-align:right;">
#         <strong>Signature:</strong><br>
#         _____________
#       </div>
#     </div>
#
#     <div style="margin-top:30px; font-size:0.9em; line-height:1.4;">
#       <strong>Description:</strong><br>
#       {{ meta.get('remarks', '') }}
#     </div>
#
#   </div>
# </div>
# """.strip()

# app/seed_data/print_formats/formats.py
from __future__ import annotations

from typing import List, Dict, Any

# =============================================================================
# DJIBOUTI (TENANT-SELECTED) - KEEP EXACTLY AS-IS (hard-coded address stays)
# =============================================================================
# ----------------------------------------------------------------------
# SALES INVOICE - DJIBOUTI (Frappe-like custom) - GLOBAL DEFAULT
# Uses your layout and DJF formatting, but mapped to your load_sales_invoice() JSON shape.
# ----------------------------------------------------------------------
SALES_INVOICE_DJIBOUTI_HTML = r"""
{% set basic = doc.get('basic_details', {}) %}
{% set party = doc.get('party_and_branch', {}) %}
{% set fin = doc.get('financial_summary', {}) %}
{% set meta = doc.get('meta', {}) %}
{% set pay = doc.get('payments_and_taxes', {}) %}
{% set line_items = doc.get('items', []) %}

{% macro djf_currency(value) -%}
  {{ "{:,.0f}".format(value or 0) }} DJF
{%- endmacro %}

<div style="font-family: Arial, sans-serif; margin:0; padding:0;">
  <div style="width:700px; margin: 0 auto; padding:10px; box-sizing:border-box;">

    <!-- HEADER -->
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:20px;">
      <div>
        {{ letter_head or "" }}
      </div>

      <div>
        <h1 style="text-align:center; margin-bottom:8px;">Sales Invoice</h1>
        <div style="text-align:center; margin-bottom:20px; font-size:0.9em; line-height:1.4;">
          <div>Saline West, Konya Road, Djibouti</div>
          <div>Email: info@cis-age.com</div>
          <div>Phone: +253 77 15 34 06</div>
        </div>
      </div>
    </div>

    <!-- BILL TO & META -->
    <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
      <div style="width:48%; font-size:0.9em; line-height:1.4;">
        <strong>BILL TO:</strong><br>
        Student Name: {{ party.get('customer_name', '') }}<br>
        Grade: {{ meta.get('custom_program') or basic.get('custom_program') or '' }}<br>
      </div>

      <div style="width:48%; text-align:right; font-size:0.9em; line-height:1.4;">
        <div><strong>Sales Invoice NO.:</strong>
          {{ basic.get('doc_no') or basic.get('code') or basic.get('id') or '' }}
        </div>
        <div><strong>DATE:</strong> {{ basic.get('posting_date', '') }}</div>
      </div>
    </div>

    <!-- ITEMS -->
    <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
      <thead>
        <tr>
          <th style="border:1px solid #000; padding:6px; text-align:left;">Description</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Qty</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Amount</th>
        </tr>
      </thead>
      <tbody>

        {% set ns = namespace(sub_total=0) %}
        {% set dis = namespace(discount=0) %}
        {% set disa = namespace(dis_amount=0) %}

        {% if line_items %}
          {% for it in line_items %}
            {% set rate = it.get('price_list_rate') if it.get('price_list_rate') is not none else it.get('rate') %}
            {% set qty  = it.get('quantity') if it.get('quantity') is not none else it.get('qty') %}
            {% set disc_pct = it.get('discount_percentage', 0) %}
            {% set disc_amt = it.get('discount_amount', 0) %}

            {% set ns.sub_total = ns.sub_total + (rate or 0) %}
            {% set dis.discount = dis.discount + (disc_pct or 0) %}
            {% set disa.dis_amount = disa.dis_amount + (disc_amt or 0) %}

            <tr>
              <td style="border:1px solid #000; padding:6px;">
                {{ it.get('item_code') or it.get('item_name') or '' }}
              </td>
              <td style="border:1px solid #000; padding:6px; text-align:right;">
                {{ qty or 0 }}
              </td>
              <td style="border:1px solid #000; padding:6px; text-align:right;">
                {{ djf_currency(rate) }}
              </td>
            </tr>
          {% endfor %}
        {% else %}
          <tr>
            <td colspan="3" style="text-align:center; padding:6px;">
              No items available
            </td>
          </tr>
        {% endif %}

      </tbody>
    </table>

    <!-- TOTALS -->
    <div style="width:100%; display:flex; justify-content:flex-end; margin-bottom:20px;">
      <table style="width:300px; border-collapse:collapse;">
        <tbody>
          <tr>
            <td style="padding:6px;">Subtotal</td>
            <td style="padding:6px; text-align:right;">
              {{ djf_currency(ns.sub_total) }}
            </td>
          </tr>
          <tr>
            <td style="padding:6px;">Discount {{ dis.discount }}%</td>
            <td style="padding:6px; text-align:right;">
              {{ djf_currency(disa.dis_amount) }}
            </td>
          </tr>
          <tr>
            <td style="padding:6px; font-weight:bold;">Total</td>
            <td style="padding:6px; text-align:right; font-weight:bold;">
              {{ djf_currency(ns.sub_total - disa.dis_amount) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- PAYMENT SCHEDULE -->
    {% if pay.get('payment_schedule') %}
      <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
        <thead>
          <tr>
            <th style="border:1px solid #000; padding:3px; text-align:left;">Payment Term</th>
            <th style="border:1px solid #000; padding:3px; text-align:right;">Due Date</th>
            <th style="border:1px solid #000; padding:3px; text-align:right;">
              Payment Amount (DJF)
            </th>
          </tr>
        </thead>
        <tbody>
          {% for row in pay.get('payment_schedule') %}
            <tr>
              <td style="border:1px solid #000; padding:3px;">
                {{ row.get('payment_term') }}
              </td>
              <td style="border:1px solid #000; padding:3px; text-align:right;">
                {{ row.get('due_date') }}
              </td>
              <td style="border:1px solid #000; padding:3px; text-align:right;">
                {{ djf_currency(row.get('payment_amount')) }}
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endif %}

    <!-- FOOTER -->
    <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
      <strong>Payment Terms:</strong><br>
      <strong>Methods:</strong> Cash | Bank Transfer
    </div>

    <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
      <strong>Bank Details:</strong><br>
      CAC Islamic Bank — 77000000212 <br>
      CAC Pay — 103002<br><br>
      Salaam African Bank — 10513889<br>
      Waafi — 7720
    </div>

    <div style="display:flex; justify-content:space-between; margin-top:40px; font-size:0.9em;">
      <div>
        <strong>Authorized By:</strong><br>
        <strong>Position:</strong>
      </div>
      <div style="text-align:right;">
        <strong>Signature:</strong><br>
        _____________
      </div>
    </div>

    <div style="margin-top:30px; font-size:0.9em; line-height:1.4;">
      <strong>Description:</strong><br>
      {{ meta.get('remarks', '') }}
    </div>

  </div>
</div>
""".strip()

PAYMENT_ENTRY_DJIBOUTI_HTML = r"""
{% macro djf_currency(value) -%}
  {{ "{:,.0f}".format((value or 0)|float) }} DJF
{%- endmacro %}

{% set grouped_map = {} %}
{% for ref in doc.references %}
  {% if ref.reference_doctype == 'Sales Invoice' and ref.reference_name %}
    {% set si = frappe.get_doc('Sales Invoice', ref.reference_name) %}
    {% set _ = grouped_map.update({
      ref.reference_name: {
        'reference_name': ref.reference_name,
        'total_amount': (si.grand_total or 0)|float,
        'outstanding_amount': (si.outstanding_amount or 0)|float
      }
    }) %}
  {% endif %}
{% endfor %}

{% set grouped_list = [] %}
{% for key, val in grouped_map.items() %}
  {% set _ = grouped_list.append(val) %}
{% endfor %}

{% set total = (grouped_list | sum(attribute='total_amount'))|float %}
{% set outstanding = (grouped_list | sum(attribute='outstanding_amount'))|float %}

{% set paid_alloc = 0 %}
{% for ref in doc.references %}
  {% set paid_alloc = paid_alloc + ((ref.allocated_amount or 0)|float) %}
{% endfor %}
{% set paid = paid_alloc if paid_alloc > 0 else (total - outstanding) %}

<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Payment {{ doc.name }}</title>
</head>
<body style="font-family: Arial, sans-serif; margin:0; padding:0;">
  <div style="width:700px; margin: 0 auto; padding:10px; box-sizing:border-box;">

    <!-- HEADER -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px;">
      <div>{{ letter_head }}</div>
      <div>
        <h1 style="text-align:center; margin-bottom:8px;">Payment</h1>
        <div style="text-align:center; margin-bottom:20px; font-size:0.9em; line-height:1.4;">
          <div>Saline West, Konya Road, Djibouti</div>
          <div>Email: info@cis-age.com</div>
          <div>Phone: +253 77 15 34 06</div>
        </div>
      </div>
    </div>

    <!-- BILL TO & META -->
    <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
      <div style="width:48%; font-size:0.9em; line-height:1.4;">
        Student Name: {{ doc.party_name or "" }}<br>
        Grade: {{ doc.custom_program or ""}}<br>
      </div>
      <div style="width:48%; text-align:right; font-size:0.9em; line-height:1.4;">
        <div><strong>Payment NO.:</strong> {{ doc.name }}</div>
        <div><strong>DATE:</strong> {{ doc.posting_date }}</div>
      </div>
    </div>

    <!-- SUMMARY -->
    <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
      <thead>
        <tr>
          <th style="border:1px solid #000; padding:6px; text-align:left;">Description</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Total</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Outstanding Amount</th>
        </tr>
      </thead>
      <tbody>
        {% for item in grouped_list %}
        <tr>
          <td style="border:1px solid #000; padding:6px;">{{ item.reference_name }}</td>
          <td style="border:1px solid #000; padding:6px; text-align:right;">{{ djf_currency(item.total_amount) }}</td>
          <td style="border:1px solid #000; padding:6px; text-align:right;">{{ djf_currency(item.outstanding_amount) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <!-- DETAILS PER INVOICE -->
    {% for item in grouped_list %}
      {% set invoice_items = frappe.get_all(
        'Sales Invoice Item',
        filters={'parent': item.reference_name},
        fields=['item_code', 'item_name', 'qty', 'rate', 'amount', 'base_rate', 'price_list_rate']
      ) %}
      {% if invoice_items %}
        <h4 style="margin-top: 30px;">Details for Invoice: {{ item.reference_name }}</h4>
        <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
          <thead>
            <tr>
              <th style="border:1px solid #000; padding:6px;">Item Code</th>
              <th style="border:1px solid #000; padding:6px;">Description</th>
              <th style="border:1px solid #000; padding:6px;">Quantity</th>
              <th style="border:1px solid #000; padding:6px; text-align:right;">Rate</th>
              <th style="border:1px solid #000; padding:6px; text-align:right;">Amount</th>
            </tr>
          </thead>
          <tbody>
            {% for inv_item in invoice_items %}
              {% set rate = (inv_item.rate or inv_item.base_rate or inv_item.price_list_rate or 0)|float %}
              {% set amount = (inv_item.amount is not none and inv_item.amount or ((inv_item.qty or 0)|float * rate))|float %}
              <tr>
                <td style="border:1px solid #000; padding:6px;">{{ inv_item.item_code or '' }}</td>
                <td style="border:1px solid #000; padding:6px;">{{ inv_item.item_name or '' }}</td>
                <td style="border:1px solid #000; padding:6px;">{{ inv_item.qty or '' }}</td>
                <td style="border:1px solid #000; padding:6px; text-align:right;">{{ djf_currency(rate) }}</td>
                <td style="border:1px solid #000; padding:6px; text-align:right;">{{ djf_currency(amount) }}</td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      {% endif %}
    {% endfor %}

    <!-- TOTALS -->
    <div style="width:100%; display:flex; justify-content:flex-end; margin-bottom:20px;">
      <table style="width:300px; border-collapse:collapse;">
        <tbody>
          <tr>
            <td style="padding:6px;">Total</td>
            <td style="padding:6px; text-align:right;">{{ djf_currency(total) }}</td>
          </tr>
          <tr>
            <td style="padding:6px;">Paid</td>
            <td style="padding:6px; text-align:right;">{{ djf_currency(paid) }}</td>
          </tr>
          <tr>
            <td style="padding:6px; font-weight:bold;">Balance due</td>
            <td style="padding:6px; text-align:right; font-weight:bold;">{{ djf_currency(outstanding) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- FOOTER -->
    <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
      <strong>Payment Terms:</strong> {{ '' }}<br>
      <strong>Methods:</strong> Cash | Bank Transfer
    </div>
    <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
      <strong>Bank Details:</strong><br>
      CAC Islamic Bank — 77000000212 <br>
      CAC Pay  — 103002<br>
      Salaam African Bank — 10513889<br>
      Waafi  — 7720<br>
    </div>
    <div style="display:flex; justify-content:space-between; margin-top:40px; font-size:0.9em;">
      <div>
        <strong>Authorized By:</strong> {{ '' }}<br>
        <strong>Position:</strong> {{ '' }}
      </div>
      <div style="text-align:right;">
        <strong>Signature:</strong><br>_____________
      </div>
    </div>
    <div style="margin-top:30px; font-size:0.9em; line-height:1.4;">
      <strong>Description:</strong><br>{{ '' }}
    </div>

  </div>
</body>
</html>
""".strip()

# Your provided purchase invoice wrapper (kept as-is).
# We keep the same variable name you requested:
PURCHASE_INVOICE_DJIBOUTI_HTML = r"""
<div class="wrapper">
	<div class="invoice_wrapper">
		<div class="header">
		  {% if letter_head and not no_letterhead -%}
    <div class="letter-head">{{ letter_head }}</div>
    {% endif %}
			<div class="bill_total_wrap">
				<div class="bill_sec">
				    	<div class="title_wrap">
						<p class="title ">{{ doc.company}}</p>
						<!-- <p class="sub_title">Privite Limited</p> -->
					</div>
					<p class="bold">Customer: {{doc.customer}}</p> 

				</div>
				<div class="total_wrap ">
					<p class="title_sec">Purchase Inv</p>
	          		<!-- <p class="bold price">USD: $1200</p> -->
					<div class="info">
						<div class="inv_name">
							<p>Inovice:</p>
							<p>{{doc.name}}</p>
						</div>
						<div class="inv_date" >
							<p >Date:</p>
							<p>{{frappe.format( doc.transaction_date, {'fieldtype': 'Date'})}}</p>
						</div>
						<div >
							<p>Sales Person:</p>
							<p>{{frappe.db.get_value("User" , doc.owner , "full_name")}}</p>
						</div>
					</div>
				</div>
			</div>
		</div>
		<div class="body">
			<div class="main_table">
				<div class="table_header">
					<div class="myrow">
						<div class="col col_no">NO.</div>
						<div class="col col_des">DESCRIPTION</div>
									<div class="col col_qty">QTY</div>
						<div class="col col_price">PRICE</div>

						<div class="col col_total">TOTAL</div>
					</div>
				</div>
				<div class="table_body">
				    {% for item in doc.items %}
					<div class="myrow">
						<div class="col col_no">
							<p>{{item.idx}}</p>
						</div>
						<div class="col col_des">
							<p class="bold">{{item.item_code}}</p>

						</div>

							<div class="col col_qty">
							<p>{{item.qty | int}}</p>
						</div>

						<div class="col col_price">
							<p>${{item.rate}}</p>
						</div>

						<div class="col col_total">
							<p>${{item.amount}}</p>
						</div>
					</div>

                    {% endfor %}
				</div>
			</div>
			<div class="paymethod_grandtotal_wrap">

				<div class="paymethod_sec" style="display: none">
					<p class="bold">Payment Method</p>
					<p>*789*000000*$#</p>
				</div>
				<div class="grandtotal_sec">
			       <p>
			            <span>Discount</span>
			            <span>${{doc.discount_amount}}</span>
			        </p>
			       	<p >
			            <span class="bold">Grand Total</span>
			            <span>${{doc.grand_total}}</span>
			        </p>

				</div>
			</div>
		</div>
		<div class="footer">
			<p>Thank you for your buinsess with us, if you have any question or concern kindly notify with us within 24 hrs. </p>
			<div class="printed">
				<p>Printed on {{frappe.utils.now()}}</p>
				<p>Printed by: {{frappe.session.user}}</p>
			</div>
		</div>
	</div>
</div>
""".strip()

# =============================================================================
# GLOBAL STANDARD (NO DJ PREFIX) - same DJ layout style but NO hard-coded address
# =============================================================================
STANDARD_SALES_INVOICE_HTML = r"""
{% set basic = doc.get('basic_details', {}) %}
{% set party = doc.get('party_and_branch', {}) %}
{% set fin = doc.get('financial_summary', {}) %}
{% set meta = doc.get('meta', {}) %}
{% set pay = doc.get('payments_and_taxes', {}) %}
{% set line_items = doc.get('items') or [] %}

<div style="font-family: Arial, sans-serif; padding:15px;">
    {{ letter_head or "" }}

    <div style="border-bottom: 2px solid #000; margin-bottom: 20px; padding-bottom: 10px;">
        <h2 style="margin:0;">Invoice: {{ basic.get('doc_no') or 'Draft' }}</h2>
        <p>Date: {{ basic.get('posting_date') }}</p>
    </div>

    <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
        <thead style="background:#f4f4f4;">
            <tr>
                <th style="border:1px solid #ddd; padding:8px; text-align:left;">Description</th>
                <th style="border:1px solid #ddd; padding:8px; text-align:right;">Qty</th>
                <th style="border:1px solid #ddd; padding:8px; text-align:right;">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% for it in line_items %}
            <tr>
                <td style="border:1px solid #ddd; padding:8px;">{{ it.get('item_name') or it.get('item_code') }}</td>
                <td style="border:1px solid #ddd; padding:8px; text-align:right;">{{ it.get('qty') or 0 }}</td>
                <td style="border:1px solid #ddd; padding:8px; text-align:right;">{{ "{:,.2f}".format(it.get('amount') or 0) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    {# --- FIXED PAYMENT SCHEDULE BLOCK --- #}
    {% set schedule = pay.get('payment_schedule') %}
    {% if schedule is iterable and schedule is not string %}
        <div style="margin-top:20px;">
            <strong>Payment Schedule:</strong>
            <table style="width:100%; margin-top:10px; border:1px solid #eee;">
                {% for row in schedule %}
                <tr>
                    <td style="padding:5px;">Due: {{ row.get('due_date') }}</td>
                    <td style="padding:5px; text-align:right;">{{ "{:,.2f}".format(row.get('payment_amount') or 0) }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    {% endif %}
</div>
""".strip()


STANDARD_PAYMENT_ENTRY_HTML = r"""
{% set curr = (doc.currency or 'DJF') if doc.currency is defined else 'DJF' %}

{% macro currency(value) -%}
  {{ "{:,.0f}".format((value or 0)|float) }} {{ curr }}
{%- endmacro %}

{% set grouped_map = {} %}
{% for ref in (doc.references or []) %}
  {% if ref.reference_doctype == 'Sales Invoice' and ref.reference_name %}
    {% if frappe is defined %}
      {% set si = frappe.get_doc('Sales Invoice', ref.reference_name) %}
      {% set _ = grouped_map.update({
        ref.reference_name: {
          'reference_name': ref.reference_name,
          'total_amount': (si.grand_total or 0)|float,
          'outstanding_amount': (si.outstanding_amount or 0)|float
        }
      }) %}
    {% else %}
      {% set _ = grouped_map.update({
        ref.reference_name: {
          'reference_name': ref.reference_name,
          'total_amount': (ref.total_amount or 0)|float,
          'outstanding_amount': (ref.outstanding_amount or 0)|float
        }
      }) %}
    {% endif %}
  {% endif %}
{% endfor %}

{% set grouped_list = [] %}
{% for key, val in grouped_map.items() %}
  {% set _ = grouped_list.append(val) %}
{% endfor %}

{% set total = (grouped_list | sum(attribute='total_amount'))|float %}
{% set outstanding = (grouped_list | sum(attribute='outstanding_amount'))|float %}

{% set paid_alloc = 0 %}
{% for ref in (doc.references or []) %}
  {% set paid_alloc = paid_alloc + ((ref.allocated_amount or 0)|float) %}
{% endfor %}
{% set paid = paid_alloc if paid_alloc > 0 else (total - outstanding) %}

<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Payment {{ doc.name }}</title>
</head>
<body style="font-family: Arial, sans-serif; margin:0; padding:0;">
  <div style="width:700px; margin: 0 auto; padding:10px; box-sizing:border-box;">

    <!-- HEADER -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px;">
      <div>{{ letter_head or "" }}</div>
      <div>
        <h1 style="text-align:center; margin-bottom:8px;">Payment</h1>
        {# Letterhead handles logo/address #}
      </div>
    </div>

    <!-- META -->
    <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
      <div style="width:48%; font-size:0.9em; line-height:1.4;">
        Party: {{ doc.party_name or "" }}<br>
      </div>
      <div style="width:48%; text-align:right; font-size:0.9em; line-height:1.4;">
        <div><strong>Payment NO.:</strong> {{ doc.name }}</div>
        <div><strong>DATE:</strong> {{ doc.posting_date }}</div>
      </div>
    </div>

    <!-- SUMMARY -->
    <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
      <thead>
        <tr>
          <th style="border:1px solid #000; padding:6px; text-align:left;">Description</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Total</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Outstanding Amount</th>
        </tr>
      </thead>
      <tbody>
        {% for item in grouped_list %}
        <tr>
          <td style="border:1px solid #000; padding:6px;">{{ item.reference_name }}</td>
          <td style="border:1px solid #000; padding:6px; text-align:right;">{{ currency(item.total_amount) }}</td>
          <td style="border:1px solid #000; padding:6px; text-align:right;">{{ currency(item.outstanding_amount) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <!-- TOTALS -->
    <div style="width:100%; display:flex; justify-content:flex-end; margin-bottom:20px;">
      <table style="width:300px; border-collapse:collapse;">
        <tbody>
          <tr>
            <td style="padding:6px;">Total</td>
            <td style="padding:6px; text-align:right;">{{ currency(total) }}</td>
          </tr>
          <tr>
            <td style="padding:6px;">Paid</td>
            <td style="padding:6px; text-align:right;">{{ currency(paid) }}</td>
          </tr>
          <tr>
            <td style="padding:6px; font-weight:bold;">Balance due</td>
            <td style="padding:6px; text-align:right; font-weight:bold;">{{ currency(outstanding) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- FOOTER -->
    <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
      <strong>Payment Terms:</strong><br>
      <strong>Methods:</strong> Cash | Bank Transfer
    </div>

    <div style="margin-bottom:20px; font-size:0.9em; line-height:1.4;">
      <strong>Bank Details:</strong><br>
      CAC Islamic Bank — 77000000212 <br>
      CAC Pay — 103002<br><br>
      Salaam African Bank — 10513889<br>
      Waafi — 7720
    </div>

    <div style="display:flex; justify-content:space-between; margin-top:40px; font-size:0.9em;">
      <div>
        <strong>Authorized By:</strong><br>
        <strong>Position:</strong>
      </div>
      <div style="text-align:right;">
        <strong>Signature:</strong><br>
        _____________
      </div>
    </div>

  </div>
</body>
</html>
""".strip()

STANDARD_PURCHASE_INVOICE_HTML = r"""
{% set basic = doc.get('basic_details', {}) %}
{% set party = doc.get('party_and_branch', {}) %}
{% set meta = doc.get('meta', {}) %}
{% set items = doc.get('items', []) %}

{% set curr = basic.get('currency') or 'DJF' %}

{% macro currency(value) -%}
  {{ "{:,.0f}".format((value or 0)|float) }} {{ curr }}
{%- endmacro %}

<div style="font-family: Arial, sans-serif; margin:0; padding:0;">
  <div style="width:700px; margin: 0 auto; padding:10px; box-sizing:border-box;">

    <!-- HEADER -->
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:20px;">
      <div>{{ letter_head or "" }}</div>
      <div>
        <h1 style="text-align:center; margin-bottom:8px;">Purchase Invoice</h1>
        {# Letterhead handles logo/address #}
      </div>
    </div>

    <!-- BILL FROM & META -->
    <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
      <div style="width:48%; font-size:0.9em; line-height:1.4;">
        <strong>BILL FROM:</strong><br>
        Supplier Name: {{ party.get('supplier_name', '') }}<br>
      </div>

      <div style="width:48%; text-align:right; font-size:0.9em; line-height:1.4;">
        <div><strong>Purchase Invoice NO.:</strong>
          {{ basic.get('doc_no') or basic.get('code') or basic.get('id') or '' }}
        </div>
        <div><strong>DATE:</strong> {{ basic.get('posting_date', '') }}</div>
      </div>
    </div>

    <!-- ITEMS -->
    <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
      <thead>
        <tr>
          <th style="border:1px solid #000; padding:6px; text-align:left;">Description</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Qty</th>
          <th style="border:1px solid #000; padding:6px; text-align:right;">Amount</th>
        </tr>
      </thead>
      <tbody>
        {% set total = namespace(val=0) %}

        {% if items %}
          {% for it in items %}
            {% set rate = it.get('rate', 0) %}
            {% set qty  = it.get('quantity') if it.get('quantity') is not none else it.get('qty') %}
            {% set line = (rate|float) * ((qty or 0)|float) %}
            {% set total.val = total.val + line %}

            <tr>
              <td style="border:1px solid #000; padding:6px;">
                {{ it.get('item_code') or it.get('item_name') or '' }}
              </td>
              <td style="border:1px solid #000; padding:6px; text-align:right;">
                {{ qty or 0 }}
              </td>
              <td style="border:1px solid #000; padding:6px; text-align:right;">
                {{ currency(line) }}
              </td>
            </tr>
          {% endfor %}
        {% else %}
          <tr>
            <td colspan="3" style="text-align:center; padding:6px;">No items available</td>
          </tr>
        {% endif %}
      </tbody>
    </table>

    <!-- TOTAL -->
    <div style="width:100%; display:flex; justify-content:flex-end; margin-bottom:20px;">
      <table style="width:300px; border-collapse:collapse;">
        <tbody>
          <tr>
            <td style="padding:6px; font-weight:bold;">Total</td>
            <td style="padding:6px; text-align:right; font-weight:bold;">
              {{ currency(total.val) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div style="margin-top:30px; font-size:0.9em; line-height:1.4;">
      <strong>Description:</strong><br>
      {{ meta.get('remarks', '') }}
    </div>

  </div>
</div>
""".strip()

# =============================================================================
# PRINT FORMAT DEFINITIONS
# - Djibouti formats are NOT bound to company_id (user selects them).
# - Global formats are company_id=None and default for doctypes.
# =============================================================================

PRINT_FORMAT_DEFS: List[Dict[str, Any]] = [

    # ---------------- GLOBAL DEFAULTS (Standard*) ----------------
    dict(
        doctype="SalesInvoice",
        module="selling",
        name="Standard Sales Invoice",
        code="standard_sales_invoice",
        company_id=None,
        default_print_language=None,
        is_standard=True,
        is_default_for_doctype=True,
        is_disabled=False,
        print_format_type="Jinja",
        custom_format=True,
        raw_printing=False,
        margin_top_mm=15,
        margin_bottom_mm=15,
        margin_left_mm=15,
        margin_right_mm=15,
        font_size_pt=None,
        google_font=None,
        align_labels_to_right=False,
        show_section_headings=False,
        show_line_breaks_after_sections=False,
        template_html=STANDARD_SALES_INVOICE_HTML,
        custom_css=None,
        external_url=None,
        raw_payload_template=None,
        default_letterhead_id=None,
        print_style_code=None,
        layout_options={"disable_global_style": True},
    ),

    dict(
        doctype="PaymentEntry",
        module="accounting",
        name="Standard Payment Receipt",
        code="standard_payment_receipt",
        company_id=None,
        default_print_language=None,
        is_standard=True,
        is_default_for_doctype=True,
        is_disabled=False,
        print_format_type="Jinja",
        custom_format=True,
        raw_printing=False,
        margin_top_mm=15,
        margin_bottom_mm=15,
        margin_left_mm=15,
        margin_right_mm=15,
        font_size_pt=None,
        google_font=None,
        align_labels_to_right=False,
        show_section_headings=False,
        show_line_breaks_after_sections=False,
        template_html=STANDARD_PAYMENT_ENTRY_HTML,
        custom_css=None,
        external_url=None,
        raw_payload_template=None,
        default_letterhead_id=None,
        print_style_code=None,
        layout_options={"disable_global_style": True},
    ),

    dict(
        doctype="PurchaseInvoice",
        module="buying",
        name="Standard Purchase Invoice",
        code="standard_purchase_invoice",
        company_id=None,
        default_print_language=None,
        is_standard=True,
        is_default_for_doctype=True,
        is_disabled=False,
        print_format_type="Jinja",
        custom_format=True,
        raw_printing=False,
        margin_top_mm=15,
        margin_bottom_mm=15,
        margin_left_mm=15,
        margin_right_mm=15,
        font_size_pt=None,
        google_font=None,
        align_labels_to_right=False,
        show_section_headings=False,
        show_line_breaks_after_sections=False,
        template_html=STANDARD_PURCHASE_INVOICE_HTML,
        custom_css=None,
        external_url=None,
        raw_payload_template=None,
        default_letterhead_id=None,
        print_style_code=None,
        layout_options={"disable_global_style": True},
    ),

    # ---------------- OPTIONAL DJIBOUTI (user-selectable, not default) ----------------
    dict(
        doctype="SalesInvoice",
        module="selling",
        name="Djibouti Sales Invoice",
        code="djibouti_sales_invoice",
        company_id=None,
        default_print_language=None,
        is_standard=False,
        is_default_for_doctype=False,
        is_disabled=False,
        print_format_type="Jinja",
        custom_format=True,
        raw_printing=False,
        margin_top_mm=15,
        margin_bottom_mm=15,
        margin_left_mm=15,
        margin_right_mm=15,
        font_size_pt=None,
        google_font=None,
        align_labels_to_right=False,
        show_section_headings=False,
        show_line_breaks_after_sections=False,
        template_html=SALES_INVOICE_DJIBOUTI_HTML,
        custom_css=None,
        external_url=None,
        raw_payload_template=None,
        default_letterhead_id=None,
        print_style_code=None,
        layout_options={"disable_global_style": True},
    ),

    dict(
        doctype="PaymentEntry",
        module="accounting",
        name="Djibouti Payment Receipt",
        code="djibouti_payment_receipt",
        company_id=None,
        default_print_language=None,
        is_standard=False,
        is_default_for_doctype=False,
        is_disabled=False,
        print_format_type="Jinja",
        custom_format=True,
        raw_printing=False,
        margin_top_mm=15,
        margin_bottom_mm=15,
        margin_left_mm=15,
        margin_right_mm=15,
        font_size_pt=None,
        google_font=None,
        align_labels_to_right=False,
        show_section_headings=False,
        show_line_breaks_after_sections=False,
        template_html=PAYMENT_ENTRY_DJIBOUTI_HTML,
        custom_css=None,
        external_url=None,
        raw_payload_template=None,
        default_letterhead_id=None,
        print_style_code=None,
        layout_options={"disable_global_style": True},
    ),

    dict(
        doctype="PurchaseInvoice",
        module="buying",
        name="Djibouti Purchase Invoice",
        code="djibouti_purchase_invoice",
        company_id=None,
        default_print_language=None,
        is_standard=False,
        is_default_for_doctype=False,
        is_disabled=False,
        print_format_type="Jinja",
        custom_format=True,
        raw_printing=False,
        margin_top_mm=10,
        margin_bottom_mm=10,
        margin_left_mm=10,
        margin_right_mm=10,
        font_size_pt=None,
        google_font=None,
        align_labels_to_right=False,
        show_section_headings=False,
        show_line_breaks_after_sections=False,
        template_html=PURCHASE_INVOICE_DJIBOUTI_HTML,
        custom_css=None,
        external_url=None,
        raw_payload_template=None,
        default_letterhead_id=None,
        print_style_code=None,
        layout_options={"disable_global_style": True},
    ),
]
