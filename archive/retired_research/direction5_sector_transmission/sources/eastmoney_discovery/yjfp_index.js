/******/ (function(modules) { // webpackBootstrap
/******/ 	// The module cache
/******/ 	var installedModules = {};
/******/
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/
/******/ 		// Check if module is in cache
/******/ 		if(installedModules[moduleId]) {
/******/ 			return installedModules[moduleId].exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = installedModules[moduleId] = {
/******/ 			i: moduleId,
/******/ 			l: false,
/******/ 			exports: {}
/******/ 		};
/******/
/******/ 		// Execute the module function
/******/ 		modules[moduleId].call(module.exports, module, module.exports, __webpack_require__);
/******/
/******/ 		// Flag the module as loaded
/******/ 		module.l = true;
/******/
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/
/******/
/******/ 	// expose the modules object (__webpack_modules__)
/******/ 	__webpack_require__.m = modules;
/******/
/******/ 	// expose the module cache
/******/ 	__webpack_require__.c = installedModules;
/******/
/******/ 	// define getter function for harmony exports
/******/ 	__webpack_require__.d = function(exports, name, getter) {
/******/ 		if(!__webpack_require__.o(exports, name)) {
/******/ 			Object.defineProperty(exports, name, { enumerable: true, get: getter });
/******/ 		}
/******/ 	};
/******/
/******/ 	// define __esModule on exports
/******/ 	__webpack_require__.r = function(exports) {
/******/ 		if(typeof Symbol !== 'undefined' && Symbol.toStringTag) {
/******/ 			Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });
/******/ 		}
/******/ 		Object.defineProperty(exports, '__esModule', { value: true });
/******/ 	};
/******/
/******/ 	// create a fake namespace object
/******/ 	// mode & 1: value is a module id, require it
/******/ 	// mode & 2: merge all properties of value into the ns
/******/ 	// mode & 4: return value when already ns object
/******/ 	// mode & 8|1: behave like require
/******/ 	__webpack_require__.t = function(value, mode) {
/******/ 		if(mode & 1) value = __webpack_require__(value);
/******/ 		if(mode & 8) return value;
/******/ 		if((mode & 4) && typeof value === 'object' && value && value.__esModule) return value;
/******/ 		var ns = Object.create(null);
/******/ 		__webpack_require__.r(ns);
/******/ 		Object.defineProperty(ns, 'default', { enumerable: true, value: value });
/******/ 		if(mode & 2 && typeof value != 'string') for(var key in value) __webpack_require__.d(ns, key, function(key) { return value[key]; }.bind(null, key));
/******/ 		return ns;
/******/ 	};
/******/
/******/ 	// getDefaultExport function for compatibility with non-harmony modules
/******/ 	__webpack_require__.n = function(module) {
/******/ 		var getter = module && module.__esModule ?
/******/ 			function getDefault() { return module['default']; } :
/******/ 			function getModuleExports() { return module; };
/******/ 		__webpack_require__.d(getter, 'a', getter);
/******/ 		return getter;
/******/ 	};
/******/
/******/ 	// Object.prototype.hasOwnProperty.call
/******/ 	__webpack_require__.o = function(object, property) { return Object.prototype.hasOwnProperty.call(object, property); };
/******/
/******/ 	// __webpack_public_path__
/******/ 	__webpack_require__.p = "";
/******/
/******/
/******/ 	// Load entry module and return exports
/******/ 	return __webpack_require__(__webpack_require__.s = 457);
/******/ })
/************************************************************************/
/******/ ({

/***/ 0:
/***/ (function(module, exports) {

module.exports = moment;

/***/ }),

/***/ 1:
/***/ (function(module, exports, __webpack_require__) {

"use strict";

/**
 * 数据字段常用公用方法
 */
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
exports.__esModule = true;
var moment_1 = __importDefault(__webpack_require__(0));
var weeks = ['日', '一', '二', '三', '四', '五', '六'];
var quarters = ['1', '1', '1', '2', '2', '2', '3', '3', '3', '4', '4', '4'];
var quarters_z = ['一', '一', '一', '二', '二', '二', '三', '三', '三', '四', '四', '四'];
var quarters0 = ['1', '1', '1', '1-2', '1-2', '1-2', '1-3', '1-3', '1-3', '1-4', '1-4', '1-4'];
var quarters0_z = ['一', '一', '一', '一-二', '一-二', '一-二', '一-三', '一-三', '一-三', '一-四', '一-四', '一-四'];
var reports = ['1季', '1季', '1季', '中', '中', '中', '3季', '3季', '3季', '年', '年', '年'];
var reports_z = ['一季', '一季', '一季', '中', '中', '中', '三季', '三季', '三季', '年', '年', '年'];
var defaultfmtconfig = {
    def: '-',
    omit: true,
    trim: undefined,
    strfmt: undefined,
    num: 432,
    smart: false,
    fix: '',
    zoom: 0,
    showcolor: false,
    showabs: false,
    qfw: false,
    colorfmt: '<span class="{color}">{value}</span>',
    gtcolor: 'red',
    ltcolor: 'green',
    colorzero: 0
};
exports["default"] = {
    /**
     * 数据字段展示格式化方法(支持数字和日期处理)
     *@param {string} value:字段,一般为字符串或数字
     *@param {string} config:配置数据
     *@param {fmtconfig} config {
         
   ```
            def?: string;// 缺省值默认 ‘-’ 优先级最高，不受其他参数影响
            datefmt?: string;//日期展示格式，如果有值的话做日期处理，有值的话除def外其他字段全部作废 优先级小于def (详见日期处理方法dateformat)
            strfmt?: any;//作为字符串处理的参数，如果有值的话做字符串处理，优先级小于def,datefmt(详见字符串处理方法strformat)
            omit?: boolean;//是否自动改为省略格式【xxxx万|xxxx亿|xxxx万亿】默认true
            trim?: boolean;//是否自动省略末尾的0，默认不省略,smart有值时候则默认为true，可单独配置
            num?: any;//保留小数位，默认值为 432（3位数保留一位小数，2位和1位数保留两位小数），可以设置保留小数规则（"5421" 代表
                五位数字及以上保存0位小数，
                四位数字及以上保留一位小数，
                二位数字及以上保留2位小数，
                一位数字保留3位小数）
            smart?: number;//是否自动精简结果【最多保留多少位有效数字】配合omit=true时使用 有值的话小数位数小于num，>1时生效
            fix?: string;//显示单位 默认空   举例 【‘%’，‘只’】
            zoom?: number;//缩放倍数（指数幂） 默认0【不放大+】  举例 【1就是放大10倍】
            showabs?: boolean//是否展示为绝对值 默认不展示
            showcolor?: boolean//是否展示颜色 默认不展示
            colorfmt?: string;//带颜色的返回模板 默认<span class="{color}">{value}</span>
            gtcolor?: string;//大于标准值的样式 默认red
            ltcolor?: string;//小于标准值的样式 默认green
            colorvalue?: number;//颜色比较使用的值，默认使用value字段
            colorzero?: number;//颜色比较标准值 默认0  与零比较
            
   ```
        }
     **/
    fieldfmt: function (value, config) {
        if (this.isEmpty(value)) {
            return (config && config.def != undefined) ? config.def : defaultfmtconfig.def;
        }
        //无配置时尝试按数据类型转换
        if ($.isEmptyObject(config)) {
            if (/^\d{2,4}(\-|\/|\.)\d{1,2}\1\d{1,2}|^\d{13}$/.test(value)) { // 有bug
                return this.dateformat(value, 'YYYY-MM-DD');
            }
            if (!$.isNumeric(value)) {
                return value;
            }
        }
        config = $.extend({}, defaultfmtconfig, config);
        if (config && config.datefmt) {
            return this.dateformat(value, config.datefmt, config.def);
        }
        if (config && config.strfmt) {
            return this.strformat(value, config.strfmt, config.def);
        }
        if (isNaN(value) || !isFinite(value)) {
            return config.def;
        }
        var oldvalue = parseFloat(value);
        var fix = "";
        var num = 2;
        //@ts-ignore
        value = oldvalue * Math.pow(10, config.zoom).toFixed(Math.abs(config.zoom));
        if (config.showabs)
            value = Math.abs(value);
        var f = config.trim ? parseFloat : function (v) { return v; };
        var abslength = Math.abs(parseInt(value)).toString().length;
        if (config.omit) {
            if (abslength > 12) {
                value = value / 1000000000000;
                abslength -= 12;
                fix = '万亿';
            }
            else if (abslength > 8) {
                value = value / 100000000;
                abslength -= 8;
                fix = '亿';
            }
            else if (abslength > 4) {
                value = value / 10000;
                abslength -= 4;
                fix = '万';
            }
        }
        if (-1 < value && value < 1)
            abslength = 0;
        if (config.smart) {
            f = parseFloat;
            config.num = "43220";
        }
        if ($.isNumeric(config.num) && config.num < 10)
            num = config.num;
        else {
            var numstr = config.num.toString();
            num = numstr.length - 1;
            for (var i = 0; i < numstr.length; i++) {
                if (abslength >= numstr[i]) {
                    num = i;
                    break;
                }
            }
        }
        value = f(this.toFixed(value, num));
        value += fix + config.fix;
        if (config.showcolor) {
            var bz = config.colorvalue;
            if (!$.isNumeric(bz))
                bz = oldvalue;
            var color = bz == config.colorzero ? '' : bz > config.colorzero ? config.gtcolor : config.ltcolor;
            //修正数字过小造成的正负号丢失问题
            if (oldvalue < 0 && config.showabs == false && value[0] != '-')
                value = '-' + value;
            value = config.colorfmt.replace('{color}', color).replace('{value}', value);
        }
        if (config.qfw)
            return value.replace(/\d+/, function (n) {
                return n.replace(/(\d)(?=(\d{3})+$)/g, function ($1) {
                    return $1 + ",";
                });
            });
        return value;
    },
    /**
     * 日期字段展示格式化方法
     * @param {string} str:字段值+
     * @param {string} fmt：日期格式 根据nomentjs 文档http://momentjs.cn/docs/
     *                  添加 {W:"星期，['日', '一', '二', '三', '四', '五', '六']
     *                  添加 {Q|q:"季度，如3月为'一|1'；6月为'二|2'"；9月为'三|3'"；12月为'四|4'"}
     *                  添加 {J|j:"季度跨度，如3月为'一|1'；6月为'一-二|1-2'"；9月为'一-三|1-3'"；12月为示'一-四|1-4'"}
     *                  添加 {B|b:"报告期，如3月为'一季|1季'；6月为'中'"；9月为'三季|3季'"；12月为'年'"}
     **/
    dateformat: function (str, fmt, def) {
        if (fmt === void 0) { fmt = 'YYYY-MM-DD'; }
        if (def === void 0) { def = '-'; }
        if (this.isEmpty(str)) {
            return def;
        }
        try {
            if (/^\d*$/.test(str)) {
                str = parseInt(str);
            }
            var ret = moment_1["default"](str);
            if (ret.isValid()) {
                var value = ret.format(fmt);
                var o = {
                    "W": weeks[ret.day()],
                    "Q": quarters_z[ret.month()],
                    "q": quarters[ret.month()],
                    "J": quarters0_z[ret.month()],
                    "j": quarters0[ret.month()],
                    "B": reports_z[ret.month()],
                    "b": reports[ret.month()]
                };
                for (var k in o) {
                    if (new RegExp("(" + k + ")").test(value)) {
                        value = value.replace(RegExp.$1, o[k]);
                    }
                }
                return value;
            }
            return def;
        }
        catch (err) {
            return def;
        }
    },
    /**
     * 字符串展示格式化方法
     * @param {string} str:字段值
     * @param {any} fmt：格式化参数，数组或对象
     **/
    strformat: function (str, fmt, def) {
        if (def === void 0) { def = '-'; }
        if (this.isEmpty(str)) {
            return def;
        }
        str = str.toString();
        if (typeof (fmt) == "object") {
            if (fmt.len && fmt.ellipsis) {
                str = this.cutstr(str, fmt.len, fmt.ellipsis, def);
            }
            for (var key in fmt) {
                if (fmt[key] !== undefined) {
                    var reg = new RegExp("({" + key + "})", "g");
                    str = str.replace(reg, fmt[key]);
                }
            }
        }
        else if (Array.isArray(fmt)) {
            fmt.forEach(function (s, i) {
                var reg = new RegExp("({)" + i + "(})", "g");
                str = str.replace(reg, s);
            });
        }
        return str;
    },
    /**
    * js截取字符串，中英文都能用
    * @param {string} str: 需要截取的字符串
    * @param {number} len: 需要截取的长度【中文算两个】
    * @param {string} ellipsis: 溢出文字
    * @returns {string} 截取后的字符串
    */
    cutstr: function (str, len, ellipsis, def) {
        if (def === void 0) { def = '-'; }
        if (this.isEmpty(str)) {
            return def;
        }
        if (typeof ellipsis != "string")
            ellipsis = "...";
        var str_length = 0;
        var str_len = 0;
        var a;
        for (var i = 0; i < str.length; i++) {
            a = str.charAt(i);
            str_length++;
            if (escape(a).length > 4) {
                //中文字符的长度经编码之后大于4  
                str_length++;
            }
            if (str_length <= len) {
                str_len++;
            }
        }
        //如果给定字符串小于指定长度，则返回源字符串；  
        if (str_length <= len) {
            return str.toString();
        }
        else {
            return str.substr(0, str_len).concat(ellipsis);
        }
    },
    /**
    * html标签转义
    * @param {string} str: 需要处理的字符串
    * @returns {string} 处理后的字符串
    */
    escapeHTML: function (text) {
        if (typeof text === 'string') {
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;')
                .replace(/`/g, '&#x60;');
        }
        return text;
    },
    /**
     * 验证数据是否存在
     * @param data
     */
    isEmpty: function (data) {
        if (data === '' || data === '-' || data === undefined || data === null || typeof data === "undefined" || data === false) {
            return true;
        }
        return false;
    },
    /**
     *
     * 分割数据转json,三期|f10
     */
    splitdatatojson: function (data, fields) {
        //console.info(fields);
        var ret = {};
        var datas = [];
        var SplitSymbol = data.SplitSymbol;
        var fs = data.FieldName.split(',');
        if (!fields)
            fields = fs;
        var _loop_1 = function () {
            itemstr = data.Data[i];
            var model = {};
            var arr = itemstr.split(SplitSymbol);
            arr.forEach(function (v, i) {
                var field = fs[i];
                if (fields.indexOf(field) > -1)
                    model[fs[i]] = v;
            });
            datas.push(model);
        };
        var itemstr;
        for (var i = 0; i < data.Data.length; i++) {
            _loop_1();
        }
        Object.keys(data).forEach(function (key) {
            if (key != "Data")
                ret[key] = data[key];
        });
        ret.datas = datas;
        //console.info(ret);
        return ret;
    },
    /**
     *
     * 数据转行情code(仅支持沪深京港)
     * 数据平台接口尽量传对象使用
     * 多层逻辑
     * obj 情况 有 SECURITY_CODE(或其他),TRADE_MARKET_CODE
     * obj 情况 有 SECUCODE
     * obj 情况 只有 SECURITY_CODE
     * string 情况  带市场格式   如   “605199.SH"
     * string 情况  6位数字    如  "300059"
     * string 情况  5位数字    如  "00001"
     *
     *
     * 都不成立的情况用第二个参数（尽量不用）
     */
    datatoquotecode: function (item, scode) {
        if (scode === void 0) { scode = ''; }
        if (typeof item === "object") {
            var code = (item === null || item === void 0 ? void 0 : item.SECURITY_CODE) || (item === null || item === void 0 ? void 0 : item.SECURITYCODE) || (item === null || item === void 0 ? void 0 : item.SCODE) || (item === null || item === void 0 ? void 0 : item.SCode) || (item === null || item === void 0 ? void 0 : item.scode) || (item === null || item === void 0 ? void 0 : item.code) || (item === null || item === void 0 ? void 0 : item.securitycode) || (item === null || item === void 0 ? void 0 : item.securityCode);
            if ((item === null || item === void 0 ? void 0 : item.TRADE_MARKET_CODE) && code.length && code.length == 6) {
                //沪
                if (item.TRADE_MARKET_CODE == "069001001001" || item.TRADE_MARKET_CODE == "069001001003" || item.TRADE_MARKET_CODE == "069001001006") {
                    return "1." + code;
                }
                //深
                else if (item.TRADE_MARKET_CODE == "069001002001" || item.TRADE_MARKET_CODE == "069001002002" || item.TRADE_MARKET_CODE == "069001002005") {
                    return "0." + code;
                }
                //京
                else if (item.TRADE_MARKET_CODE == "069001017") {
                    return "0." + code;
                }
                //新三板，老三版
                else if (item.TRADE_MARKET_CODE == "069001004001" || item.TRADE_MARKET_CODE == "069001004002") {
                    return "0." + code;
                }
            }
            if (item === null || item === void 0 ? void 0 : item.SECUCODE) {
                item = item.SECUCODE;
            }
            else if (code) {
                item = code;
            }
            else {
                item = scode;
            }
        }
        if (typeof item === "string") {
            var codes = item.split('.');
            if (codes.length == 2) {
                var mkt = '';
                if (codes[1].toUpperCase() == "SH")
                    mkt = '1';
                else if (codes[1].toUpperCase() == "SZ")
                    mkt = '0';
                else if (codes[1].toUpperCase() == "BJ")
                    mkt = '0';
                else if (codes[1].toUpperCase() == "NQ")
                    mkt = '0';
                else if (codes[1].toUpperCase() == "HK")
                    mkt = '116';
                return mkt + "." + codes[0];
            }
            if (/\d{6}/.test(item)) {
                item = /\d{6}/.exec(item)[0];
                var one = item.substr(0, 1);
                var three = item.substr(0, 3);
                if (one == "4" || one == "8" || three == "920") {
                    //沪
                    return "0." + item;
                }
                else if (one == "5" || one == "6" || one == "9") {
                    //京
                    return "1." + item;
                }
                else {
                    if (three == "009" || three == "126" || three == "110" || three == "201" || three == "202" || three == "203" || three == "204") {
                        //沪
                        return "1." + item;
                    }
                    else {
                        //深   其它
                        return "0." + item;
                    }
                }
            }
            else if (/^\d{5}/.test(item)) {
                item = /^\d{5}/.exec(item)[0];
                //港
                return "116." + item;
            }
        }
    },
    fmtsname: function (name, len) {
        if (len === void 0) { len = 8; }
        return "<span title=\"" + this.escapeHTML(this.strformat(name)) + "\">" + this.cutstr(name, len) + "</span>";
    },
    getUrlParam: function (name) {
        var reg = new RegExp("(^|&)" + name + "=([^&]*)(&|$)", "i");
        var r = window.location.search.substr(1).match(reg);
        if (r != null)
            return decodeURIComponent(r[2]);
        return null;
    },
    toFixed: function (value, num) {
        var power = Math.pow(10, num);
        return (Math.round(value * power) / power).toFixed(num);
    },
    enhancedXSSCheck: function (input) {
        if (typeof input !== 'string') {
            return null;
        }
        // 检测HTML标签和script标签的正则表达式
        var htmlTagRegex = /<[^>]+>/i;
        var scriptTagRegex = /<script\b[^>]*>([\s\S]*?)<\/script>/gi;
        // 检测到任何HTML标签或script标签就返回null
        if (htmlTagRegex.test(input) || scriptTagRegex.test(input)) {
            console.log(input);
            return false;
        }
        // 安全的内容直接返回
        return true;
        // return xssPatterns.some(pattern => pattern.test(input)) ? false : true;
    }
};


/***/ }),

/***/ 18:
/***/ (function(module, exports, __webpack_require__) {

"use strict";

var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
exports.__esModule = true;
//@ts-nocheck
/**
 * hq 提示行情
 */
var hq_html_1 = __importDefault(__webpack_require__(19));
var globalTimeoutHover, globalTimeoutHoverOut;
if ($(".hqpop").length <= 0) {
    $("body").append(hq_html_1["default"]);
}
var $pop = $(".hqpop");
var $name = $(".hqpop_content_name", $pop);
var $more = $(".hqpop_content_more a", $pop);
var $ka = $(".hqpop_content_tablist a", $pop).eq(1);
var $wka = $(".hqpop_content_tablist a", $pop).eq(2);
var $mka = $(".hqpop_content_tablist a", $pop).eq(3);
var $imgbox = $(".hqpop_content_img", $pop);
var wwidth = $(window).width();
var wheight = $(window).height();
var popheight = 340;
var popwidth = 600;
$(document).on("mouseover", ".hqPopCls", function (event) {
    if (!!globalTimeoutHoverOut) {
        clearTimeout(globalTimeoutHoverOut);
    }
    var _this = $(this);
    var mkt = _this.data("mkt");
    var code = '' + _this.data("code");
    //临时去掉京市的股票提示
    // if (code && (code[0] == '4' || code[0] == '8'))
    //   return
    var name = _this.data("name");
    var width = _this.width();
    var height = _this.height();
    var left = _this.offset().left + width;
    var top = _this.offset().top + height;
    var wstop = $("html").scrollTop() || $("body").scrollTop();
    var wsleft = $("html").scrollLeft() || $("body").scrollLeft();
    if (wheight + height - (top - wstop) < popheight)
        top = top - height - popheight;
    if (wwidth + width - (left - wsleft) < popwidth)
        left = left - width - popwidth;
    globalTimeoutHover = setTimeout(function () {
        $name.html(name);
        $more.attr("href", "//quote.eastmoney.com/concept/" + mkt + code + ".html");
        $ka.attr("href", "//quote.eastmoney.com/concept/" + mkt + code + ".html#fschart-k");
        $wka.attr("href", "//quote.eastmoney.com/concept/" + mkt + code + ".html#fschart-wk");
        $mka.attr("href", "//quote.eastmoney.com/concept/" + mkt + code + ".html#fschart-mk");
        $imgbox.html("<img width=\"578\" height=\"276\" src='//webquotepic.eastmoney.com/GetPic.aspx?nid=" + (mkt == "sh" ? 1 : 0) + "." + code + "&imageType=r&token=b2884a393a59ad64002292a3e90d46a5'/>");
        $pop.css({ left: left, top: top });
        $pop.show();
    }, 400);
});
$(document).on("mouseout", ".hqPopCls", function (event) {
    if (!!globalTimeoutHover) {
        clearTimeout(globalTimeoutHover);
    }
    globalTimeoutHoverOut = setTimeout(function () {
        $pop.hide();
    }, 400);
});
$(document).on("mouseenter", ".hqpop", function (event) {
    if (!!globalTimeoutHoverOut) {
        clearTimeout(globalTimeoutHoverOut);
    }
});
$(document).on("mouseleave", ".hqpop", function (event) {
    $pop.hide();
});


/***/ }),

/***/ 19:
/***/ (function(module, exports) {

module.exports = "<style>\r\n  .hqpop {\r\n    width: 580px;\r\n    height: 315px;\r\n    padding: 3px;\r\n    border: 2px solid #bbb;\r\n    background-color: #fff;\r\n    position: absolute;\r\n    z-index: 99999;\r\n  }\r\n  .hqpop .hqpop_content_name {\r\n    margin-left: 10px;\r\n    line-height: 30px;\r\n    height: 30px;\r\n    width: 100px;\r\n    float: left;\r\n    font-size: 16px;\r\n  }\r\n  .hqpop .hqpop_content_tablist a {\r\n    margin-top: 3px;\r\n    float: left;\r\n    display: inline-block;\r\n    border: solid 1px #4267a0;\r\n    border-left: none;\r\n    padding: 2px 10px;\r\n    cursor: pointer;\r\n    height: 16px;\r\n    line-height: 16px;\r\n  }\r\n  .hqpop .hqpop_content_tablist a.at {\r\n    background-color: #4267a0;\r\n    border-left: solid 1px #4267a0;\r\n    color: white;\r\n  }\r\n  .hqpop .hqpop_content_more {\r\n    float: right;\r\n    font-size: 14px;\r\n    padding-right: 10px;\r\n    line-height: 25px;\r\n  }\r\n  .hqpop .hqpop_content_img {\r\n  }\r\n</style>\r\n<div class=\"hqpop\" style=\"display: none\">\r\n  <div class=\"hqpop_content\">\r\n    <div class=\"hqpop_content_name\"></div>\r\n    <div class=\"hqpop_content_tablist\">\r\n      <a class=\"at\">分时</a>\r\n      <a>日K</a>\r\n      <a>周K</a>\r\n      <a>月K</a>\r\n    </div>\r\n    <div class=\"hqpop_content_more\"><a>更多</a></div>\r\n    <div class=\"hqpop_content_img\"></div>\r\n  </div>\r\n</div>\r\n";

/***/ }),

/***/ 2:
/***/ (function(module, exports) {

function getUrlParam(name){
    var urlpara = location.search;
    var par = {};
    if (urlpara != "") {
      urlpara = urlpara.substring(1, urlpara.length);
      var para = urlpara.split("&");
      var parname;
      var parvalue;
      for (var i = 0; i < para.length; i++) {
        parname = para[i].substring(0, para[i].indexOf("="));
        parvalue = para[i].substring(para[i].indexOf("=") + 1, para[i].length);
        par[parname] = parvalue;
      }
    }
    if(typeof (par[name]) != "undefined"){
      return par[name];
    }
    else{
      return null;
    }
  }

module.exports = {
  development: {
    dataurl: function(){
      // return '//reportapi.uat.emapd.com/'
      return '//reportapi-uat.eastmoney.com/'
    },
    quoteurl: function(){
      let env = getUrlParam('myenv') || '';
      if(env == 'prod') {
        return '//push2.eastmoney.com/'
      }
      return '//push2test.eastmoney.com/'
      // return '//push2-uatfj.eastmoney.com/'
    },
    quotehisurl: function(){
      // return '//push2test.eastmoney.com/'
      return '//push2his-uatfj.eastmoney.com/'
    },    
    dcfmurl: function(){
      return '//dcfm.eastmoney.com/' 
    }, 
    anoticeurl: function(){
      // return '//np-anotice-stock.eastmoney.com/'
      return '//np-anotice-stock-test.eastmoney.com/'
    },
    cnoticeurl: function(){
      return '//np-cnotice-stock-test.eastmoney.com/'
    },
    datacenter: function(){
      // return '//datacenter-web.eastmoney.com/'
      return '//testdatacenter.eastmoney.com/'
      // return '//betadatacenter.eastmoney.com/'
      let env = getUrlParam('myenv') || '';
      if(env == 'prod') {
        return '//datacenter-web.eastmoney.com/'
      }
      return '//betadatacenter.eastmoney.com/'
      // return '//testdatacenter.eastmoney.com/'
    },
    datacenter2: function(){
      // return '//datacenter-web.eastmoney.com/'
      return '//testdatacenter.eastmoney.com/'
      // return '//betadatacenter.eastmoney.com/'
      // let env = getUrlParam('myenv') || '';
      // if(env == 'prod') {
      //   return '//datacenter-web.eastmoney.com/'
      // }
      // return '//testdatacenter.eastmoney.com/'
    },
    soapi: function(){
      return '//searchapi.eastmoney.com/'
    }, 
    cmsdataapi: function(){
      return '//cmsdataapi.eastmoney.com/'
    },
    newsinfo: function(){
      return '//newsinfo.eastmoney.com/'
    },
    url: function(){
      return ''
    },
    cmsapi : function () {
      return '//np-listapi.eastmoney.com//'
    },
    futsseapi: function () {
      // return '//futsseapi.eastmoney.com/'
      return '//futssetest.eastmoney.com/'
    },
    futssstatic: function () {
      // return '//futsse-static.eastmoney.com/'
      return '//static.futssetest.eastmoney.com/'
    }
  },
  zptest: {
    dataurl: function(){
      // return '//reportapi.eastmoney.com/'
      // return '//reportapi.uat.emapd.com/'
      return '//reportapi-uat.eastmoney.com/'

    },
    quoteurl: function(){
      let env = getUrlParam('myenv') || '';
      if(env == 'prod') {
        return '//push2.eastmoney.com/'
      }
      return '//push2test.eastmoney.com/'
      // return '//push2test.eastmoney.com/'
      // return '//push2-uatfj.eastmoney.com/'
    },
    quotehisurl: function(){
      // return '//push2test.eastmoney.com/'
      return '//push2his-uatfj.eastmoney.com/'
    }, 
    dcfmurl: function(){
      return '//dcfm.eastmoney.com/'
    },
    anoticeurl: function(){
      return '//np-anotice-stock-test.eastmoney.com/'
    },
    cnoticeurl: function(){
      // return '//np-cnotice-stock-test.emapd.com/'
      return '//np-cnotice-stock-test.eastmoney.com/'
    },
    datacenter: function(){
      return '//testdatacenter.eastmoney.com/'
      // return '//betadatacenter.eastmoney.com/'
      // return '//datacenter-web.eastmoney.com/'
      let env = getUrlParam('myenv') || '';
      if(env == 'prod') {
        return '//datacenter-web.eastmoney.com/'
      }
      return '//betadatacenter.eastmoney.com/'
      // return '//testdatacenter.eastmoney.com/'
    },
    datacenter2: function(){
      // return '//datacenter-web.eastmoney.com/'
      return '//testdatacenter.eastmoney.com/'
      // return '//betadatacenter.eastmoney.com/'
      // let env = getUrlParam('myenv') || '';
      // if(env == 'prod') {
      //   return '//datacenter-web.eastmoney.com/'
      // }
      // return '//testdatacenter.eastmoney.com/'
    },
    soapi: function(){
      return '//searchapi.eastmoney.com/'
    },    
    cmsdataapi: function(){
      return '//cmsdataapi.eastmoney.com/'
    },
    newsinfo: function(){
      return '//newsinfo.eastmoney.com/'
    },
    url: function(){
      return ''
    },
    cmsapi : function () {
      return '//np-listapi.eastmoney.com//'
    },
    futsseapi: function () {
       return '//futssetest.eastmoney.com/'
      // return '//futsseapi.eastmoney.com/'
    },
    futssstatic: function () {
      // return '//futsse-static.eastmoney.com/'
      return '//static.futssetest.eastmoney.com/'
    }
  },
  gray: {
    dataurl: function(){
      return '//reportapi.eastmoney.com/'
    },
    quoteurl: function(){
      return '//push2.eastmoney.com/'
    },
    quotehisurl: function(){
      return '//push2his-uatfj.eastmoney.com/'
    },      
    dcfmurl: function(){
      return '//dcfm.eastmoney.com/'
    },
    anoticeurl: function(){
      return '//np-anotice-stock.eastmoney.com/'
    },
    cnoticeurl: function(){
      return '//np-cnotice-stock.eastmoney.com/'
    },
    datacenter: function(){
      return '//graydatacenter.eastmoney.com/web/'
    },
    datacenter2: function(){
      return '//graydatacenter.eastmoney.com/web/'
    },
    soapi: function(){
      return '//searchapi.eastmoney.com/'
    },      
    cmsdataapi: function(){
      return '//cmsdataapi.eastmoney.com/'
    },
    newsinfo: function(){
      return '//newsinfo.eastmoney.com/'
    },
    url: function(){
      return ''
    },
    cmsapi : function () {
      return '//np-listapi.eastmoney.com//'
    },
    futsseapi: function () {
       return '//futssetest.eastmoney.com/'
      // return '//futsseapi.eastmoney.com/'
    },
    futssstatic: function () {
      // return '//futsse-static.eastmoney.com/'
      return '//static.futssetest.eastmoney.com/'
    }
  },
  production: {
    dataurl: function(){
      return '//reportapi.eastmoney.com/'
    },
    quoteurl: function(){
      return '//push2.eastmoney.com/'
    },
    quotehisurl: function(){
      return '//push2his.eastmoney.com/'
    },      
    dcfmurl: function(){
      return '//dcfm.eastmoney.com/'
    },
    anoticeurl: function(){
      return '//np-anotice-stock.eastmoney.com/'
    },
    cnoticeurl: function(){
      return '//np-cnotice-stock.eastmoney.com/'
    },
    datacenter: function(){
      return '//datacenter-web.eastmoney.com/'
    },
    datacenter2: function(){
      return '//datacenter-web.eastmoney.com/'
    },
    soapi: function(){
      return '//searchapi.eastmoney.com/'
    },      
    cmsdataapi: function(){
      return '//cmsdataapi.eastmoney.com/'
    },
    newsinfo: function(){
      return '//newsinfo.eastmoney.com/'
    },
    url: function(){
      return ''
    },
    cmsapi : function () {
      return '//np-listapi.eastmoney.com//'
    },
    futsseapi: function () {
      return '//futsseapi.eastmoney.com/'
    },
    futssstatic: function () {
      return '//futsse-static.eastmoney.com/'
    }
  },
  getParam: function(name){
    var urlpara = location.search;
    var par = {};
    if (urlpara != "") {
      urlpara = urlpara.substring(1, urlpara.length);
      var para = urlpara.split("&");
      var parname;
      var parvalue;
      for (var i = 0; i < para.length; i++) {
        parname = para[i].substring(0, para[i].indexOf("="));
        parvalue = para[i].substring(para[i].indexOf("=") + 1, para[i].length);
        par[parname] = parvalue;
      }
    }
    if(typeof (par[name]) != "undefined"){
      return par[name];
    }
    else{
      return null;
    }
  },
  getWebPath: function (name) {
    var env=(window.service&&service.ENV)||this.getParam('env');

    // env = "production"

    if (env&&this[env]) {
      return this[env][name]()
    }
    return this.production[name]()
  }
}



/***/ }),

/***/ 457:
/***/ (function(module, exports, __webpack_require__) {

"use strict";

var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
exports.__esModule = true;
/**
 * 分红送配首页
 */
__webpack_require__(18);
var webconfig = __webpack_require__(2);
var fieldtools_1 = __importDefault(__webpack_require__(1));
function getMkt(mktCode) {
    var mkt = "";
    switch (mktCode) {
        case "069001001001":
        case "069001001003":
        case "069001001006":
            mkt = "sh";
            break;
        case "069001002002":
        case "069001002001":
        case "069001002005":
            mkt = "sz";
            break;
        default:
            break;
    }
    return mkt;
}
var opt = {
    dataurl: {
        hostname: "datacenter",
        url: "api/data/v1/get",
        params: {
            reportName: "RPT_SHAREBONUS_DET",
            columns: "ALL",
            quoteColumns: "",
            js: '{"data":(x),"pages":(tp)}',
            source: "WEB",
            client: "WEB"
        }
    },
    sortname: "PLAN_NOTICE_DATE",
    urlkeyvalues: {
        pagenumber: "pageNumber",
        pagesize: "pageSize",
        sortname: "sortColumns",
        sortorder: "sortTypes"
    },
    totalpagesfield: 'result.pages',
    datafield: 'result.data',
    filteroptions: [
        {
            name: "filter",
            fieldname: "mkt",
            filterselector: "#filter_mkt",
            filtersoptionselector: "a",
            selectedclass: "at",
            values: emmap.mkt_type
        },
        {
            name: "filter",
            fieldname: "date",
            filterselector: "#filter_date",
            filtersoptionselector: "option",
            values: function (value) {
                return "(REPORT_DATE='" + value + "')";
            },
            handle: function (filter, that) {
                $(".reportdate").html(fieldtools_1["default"].dateformat(filter.value, "YYYY年B报"));
            }
        },
        {
            name: "filter",
            fieldname: "type",
            filterselector: "#filter_type",
            filtersoptionselector: "li",
            values: function (value, options) {
                if (value == "fhya")
                    return "(EX_DIVIDEND_DAYS<0)";
                else if (value == "yssfa" && !options.filteroptions[7].value)
                    return "(EX_DIVIDEND_DAYS>=0)"; //已实施方案
            },
            handle: function (filter, that) {
                if (filter.value == "yssfa") {
                    $("#filter_group1").hide();
                    $("#filter_group2").show();
                }
                else {
                    $("#filter_group1").show();
                    $("#filter_group2").hide();
                }
                that.refresh({ tabletype: filter.value }, true);
                return false;
            }
        },
        {
            name: "filter",
            fieldname: "TOTAL_SHARES",
            filterselector: "#filter_TotalEquity",
            filtersoptionselector: "option",
            values: function (value, options) {
                if (options.filteroptions[2].value == "yssfa")
                    return "";
                return value;
            }
        },
        {
            name: "filter",
            fieldname: "BVPS",
            filterselector: "#filter_ROE",
            filtersoptionselector: "option",
            values: function (value, options) {
                if (options.filteroptions[2].value == "yssfa")
                    return "";
                return value;
            }
        },
        {
            name: "filter",
            fieldname: "PER_CAPITAL_RESERVE",
            filterselector: "#filter_PFPS",
            filtersoptionselector: "option",
            values: function (value, options) {
                if (options.filteroptions[2].value == "yssfa")
                    return "";
                return value;
            }
        },
        {
            name: "filter",
            fieldname: "PER_UNASSIGN_PROFIT",
            filterselector: "#filter_UDPPS",
            filtersoptionselector: "option",
            values: function (value, options) {
                if (options.filteroptions[2].value == "yssfa")
                    return "";
                return value;
            }
        },
        {
            name: "filter",
            fieldname: "EX_DIVIDEND_DAYS",
            filterselector: "#filter_YCQTS",
            filtersoptionselector: "option",
            values: function (value, options) {
                if (options.filteroptions[2].value == "yssfa")
                    return value;
                return "";
            }
        },
        {
            name: "filter",
            fieldname: "BONUS_IT_RATIO",
            filterselector: "#filter_TPTS",
            filtersoptionselector: "option",
            values: function (value, options) {
                if (options.filteroptions[2].value == "yssfa")
                    return value;
                return "";
            }
        }
    ],
    columns: {
        SECURITY_CODE: {
            formatter: function (value, item, i, field) {
                var mkt = getMkt(item.MARKET_TYPE);
                return "<a class=\"hqPopCls\" data-code=\"" + value + "\" data-mkt=\"" + mkt + "\" data-name=\"" + item.SECURITY_NAME_ABBR + "\" href=\"//quote.eastmoney.com/unify/r/" + fieldtools_1["default"].datatoquotecode(value) + "\">" + value + "</a>";
            },
        },
        SECURITY_NAME_ABBR: {
            formatter: function (value, item, i, field) {
                var mkt = getMkt(item.MARKET_TYPE);
                return "<a class=\"hqPopCls\" data-code=\"" + item.SECURITY_CODE + "\" data-mkt=\"" + mkt + "\" data-name=\"" + item.SECURITY_NAME_ABBR + "\" href=\"/stockdata/" + item.SECURITY_CODE + ".html\">" + fieldtools_1["default"].fmtsname(value) + "</a>";
            },
        },
        xg: {
            formatter: function (value, item, i, field) {
                return ('<a href="/yjfp/detail/' +
                    item.SECURITY_CODE +
                    ".html\" class='red'>详细</a>&nbsp;<a href=\"/bbsj/" +
                    item.SECURITY_CODE +
                    '.html">报表</a>');
            },
        },
        BONUS_IT_RATIO: {
            formatter: function (value, item, i, field) {
                var str = "-";
                if ($.isNumeric(item.BONUS_RATIO)) {
                    if (item.BONUS_RATIO > 0)
                        str = "10送" + item.BONUS_RATIO.toFixed(1);
                }
                if ($.isNumeric(item.IT_RATIO)) {
                    if (item.IT_RATIO > 0)
                        str =
                            str == "-"
                                ? "10转" + item.IT_RATIO.toFixed(1)
                                : str + "转" + item.IT_RATIO.toFixed(1);
                }
                return str;
            },
        },
        BONUS_RATIO: {
            formatter: function (value, item, i, field) {
                if ($.isNumeric(value)) {
                    if (value > 0)
                        return "10送" + value.toFixed(1);
                }
                return "-";
            },
        },
        IT_RATIO: {
            formatter: function (value, item, i, field) {
                if ($.isNumeric(value)) {
                    if (value > 0)
                        return "10转" + value.toFixed(1);
                }
                return "-";
            },
        },
        PRETAX_BONUS_RMB: {
            formatter: function (value, item, i, field) {
                if ($.isNumeric(value)) {
                    return "10派" + fieldtools_1["default"].fieldfmt(value, { smart: true });
                }
                return "-";
            },
        },
        DIVIDENT_RATIO: {
            formatter: { zoom: 2 }
        },
        TOTAL_SHARES: {
            formatter: { smart: true, zoom: -8, trim: false }
        },
        PLAN_NOTICE_DATE: {
            formatter: function (value, item, i, field) {
                return "<span title=\"" + fieldtools_1["default"].dateformat(value, "YYYY-MM-DD") + "\">" + fieldtools_1["default"].dateformat(value, "MM-DD") + "</span>";
            }
        },
        EQUITY_RECORD_DATE: {
            formatter: function (value, item, i, field) {
                return "<span title=\"" + fieldtools_1["default"].dateformat(value, "YYYY-MM-DD") + "\">" + fieldtools_1["default"].dateformat(value, "MM-DD") + "</span>";
            }
        },
        EX_DIVIDEND_DATE: {
            formatter: function (value, item, i, field) {
                return "<span title=\"" + fieldtools_1["default"].dateformat(value, "YYYY-MM-DD") + "\">" + fieldtools_1["default"].dateformat(value, "MM-DD") + "</span>";
            }
        },
        NOTICE_DATE: {
            formatter: function (value, item, i, field) {
                return "<span title=\"" + fieldtools_1["default"].dateformat(value, "YYYY-MM-DD") + "\">" + fieldtools_1["default"].dateformat(value, "MM-DD") + "</span>";
            }
        },
        D10_CLOSE_ADJCHRATE: {
            formatter: { showcolor: true },
        },
        BD10_CLOSE_ADJCHRATE: {
            formatter: { showcolor: true },
        },
        D30_CLOSE_ADJCHRATE: {
            formatter: { showcolor: true },
        },
        EX_DIVIDEND_DAYS: {
            formatter: { num: 0 }
        }
    },
    onPreLoad: function (that, dataajaxOptions) {
        console.info(dataajaxOptions.data.filter);
    },
    onPreBody: function (data) {
        if (data && data[0])
            $(".reportdate").html(fieldtools_1["default"].dateformat(data[0].REPORT_DATE, "YYYY年B报"));
    }
};
$.ajax({
    url: webconfig.getWebPath("datacenter") + "api/data/v1/get",
    type: "GET",
    dataType: "jsonp",
    data: {
        reportName: "RPT_DATE_SHAREBONUS_DET",
        columns: "ALL",
        quoteColumns: "",
        pageNumber: 1,
        sortColumns: "REPORT_DATE",
        sortTypes: -1,
        source: "WEB",
        client: "WEB"
    }
}).then(function (json) {
    var list = json && json.result && json.result.data;
    if (list) {
        var optshtml_1 = "";
        list.forEach(function (item) {
            var datastr = fieldtools_1["default"].dateformat(item.REPORT_DATE);
            if (datastr.length > 6)
                optshtml_1 += "<option value=\"" + datastr + "\">" + datastr + "</option>";
        });
        $("#filter_date").html(optshtml_1);
        $("#dataview").emdataview(opt);
    }
});


/***/ })

/******/ });
//# sourceMappingURL=index.js.map